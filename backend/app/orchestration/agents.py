"""业务 Agent 注册表（p5.1b）——配置驱动的 Agent 装配处（设计文档 §五 能力池）。

两层：
  · 工具池：build_default_registry 装配全部真实工具（p5.1a：db_query / rag_retrieve）。
  · AgentSpec：config/agents.yaml 里每个 agent_type 的角色提示词 + 工具白名单；
    build_registry_for_spec 按白名单裁剪出该 Agent 可见的工具集。

agent_type 与 config/planner.yaml 的 agent 字段一致（data_cleaning / data_analysis /
report_generation / rag_retrieval / visualization / image_restore），另有 general 兜底。
未注册的 agent_type 一律回落 general（不猜、不编）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy.engine import Engine

from ..core.config import settings
from .tools import ToolRegistry
from .tools_db import make_db_query_tool
from .tools_doc import make_read_document_tool
from .tools_rag import make_rag_retrieve_tool
from .tools_table import make_analyze_table_tool, make_clean_table_tool
from .tools_write import make_write_document_tool

logger = logging.getLogger(__name__)

FALLBACK_AGENT = "general"


@dataclass(frozen=True)
class AgentSpec:
    agent_type: str
    name: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 工具池（全部真实工具；各 Agent 按白名单取子集）
# --------------------------------------------------------------------------- #
def build_default_registry(engine: Engine | None, username: str | None = None) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        "db_query",
        make_db_query_tool(engine, max_rows=settings.db_query_max_rows),
        description=(
            "查询公司业务库（只读）。参数: sql（单条 SELECT 语句；自动追加 LIMIT，"
            "禁止 INSERT/UPDATE/DELETE 等写操作）。适用于查员工/订单/台账等结构化数据。"
        ),
    )
    reg.register(
        "rag_retrieve",
        make_rag_retrieve_tool(
            base_url=settings.rag_base_url,
            internal_secret=settings.rag_internal_secret,
            username=settings.rag_service_username,
        ),
        description=(
            "检索公司知识库（制度/文档问答），返回答案与来源清单。参数: query（检索问题）。"
            "适用于查公司制度、流程、文档内容等非结构化知识。"
        ),
    )
    owner = (username or "").strip().strip("/") or None
    doc_base = str(Path(settings.documents_dir) / owner) if owner else settings.documents_dir
    if owner:
        read_desc = (
            "读取当前登录用户上传目录中的文件（支持 .md/.txt/.json/.csv/.docx/.xlsx/.pdf）。"
            "表格只返回表头、行数和前 20 行，不是整表。"
            "参数 file_name 只写文件名，例如 网站备案办事指南.pdf。"
            "查找目录由系统按当前用户确定，不要传本机绝对路径；写成「用户名/文件名」也可以。"
            "文件不存在时不要反复重试，直接如实告知用户。"
        )
    else:
        read_desc = (
            "读取文档目录内指定文件（支持 .md/.txt/.json/.csv/.docx/.xlsx/.pdf）。"
            "表格只返回表头、行数和前 20 行。"
            "参数: file_name（文档目录内的相对路径；当前登录用户上传的文件在 "
            "'<用户名>/' 子目录下，例如 dev/handbook.md）。"
            "适用于需要引用某份文档原文/做摘要的场景。"
            "注意：文件不存在时不要反复重试，直接如实告知用户文件名可能不对。"
        )
    reg.register(
        "read_document",
        make_read_document_tool(
            base_dir=doc_base, max_chars=settings.doc_read_max_chars, owner=owner
        ),
        description=read_desc,
    )
    reg.register(
        "clean_table",
        make_clean_table_tool(base_dir=doc_base, owner=owner),
        description=(
            "清洗上传的表格（csv、xlsx，或对象数组 json），不修改原文件。"
            "会去掉全空行、全空列、重复的表头行和完全相同的行；去掉首尾空白，"
            "并把 null、N/A、无、- 视为空。不用平均数填缺失，也不因异常值删行。"
            "参数 file_name：文件名。key_columns：可选，关键列名；这些列为空的行会从结果剔除并单独计数。"
            "sheet：xlsx 工作表名，不填则用第一张。返回 clean_id，接着交给 analyze_table。"
        ),
    )
    reg.register(
        "analyze_table",
        make_analyze_table_tool(base_dir=doc_base, owner=owner),
        description=(
            "只分析 clean_table 返回的表。参数 clean_id 必填，不能传原始文件名。"
            "group_by：分组列，可空。metrics：[{column, agg}]，agg 取 count、sum、mean、min、max、count_distinct；"
            "不传 metrics 时只计数。filters：[{column, op, value}]，op 取 eq、ne、contains、gt、gte、lt、lte。"
            "sum/mean/min/max 遇到不能转成数字的格子会跳过并计数，不会当成 0。"
        ),
    )
    reg.register(
        "write_document",
        make_write_document_tool(base_dir=doc_base, owner=owner),
        description=(
            "把已经得到的结论写成 md 或 docx，不画图，也不生成 xlsx。"
            "参数 title：标题。content：正文，数字必须来自此前的工具结果。"
            "format：md 或 docx。clean_id：若结论来自清洗后的表，传入它，文末会写上来源和行数。"
            "返回 file_name。失败就说明没生成，不要给一个不存在的下载地址。"
        ),
    )
    return reg


def build_registry_for_spec(spec: AgentSpec, base: ToolRegistry) -> ToolRegistry:
    """按 AgentSpec 的工具白名单裁剪；白名单里的未知名记 warning（对 Agent 不可见=能力缺失）。"""
    reg = ToolRegistry()
    for name in spec.tools:
        if not base.has(name):
            logger.warning("Agent %s 声明了未注册工具 %s（跳过=对该 Agent 能力缺失）", spec.agent_type, name)
            continue
        desc = next((d["description"] for d in base.describe() if d["name"] == name), "")
        reg.register(name, base._tools[name], desc)  # noqa: SLF001 - 同包内装配
    return reg


# --------------------------------------------------------------------------- #
# AgentSpec 加载（config/agents.yaml）
# --------------------------------------------------------------------------- #
def _resolve_agents_path() -> Path:
    if settings.agents_config:
        p = Path(settings.agents_config)
        if p.exists():
            return p
    candidates = [
        Path("/app/config/agents.yaml"),
        Path(__file__).resolve().parents[2] / "config" / "agents.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("agents.yaml 未找到（设 AGENTS_CONFIG 或放 backend/config/agents.yaml）")


def load_agent_specs() -> dict[str, AgentSpec]:
    raw = yaml.safe_load(_resolve_agents_path().read_text(encoding="utf-8")) or {}
    specs: dict[str, AgentSpec] = {}
    for agent_type, item in (raw.get("agents") or {}).items():
        item = item or {}
        specs[str(agent_type)] = AgentSpec(
            agent_type=str(agent_type),
            name=str(item.get("name", agent_type)),
            system_prompt=str(item.get("system_prompt", "")).strip(),
            tools=[str(t) for t in (item.get("tools") or [])],
        )
    return specs


def get_agent_spec(agent_type: str | None) -> AgentSpec:
    """按 agent_type 取 spec；未注册回落 general。"""
    specs = load_agent_specs()
    key = (agent_type or FALLBACK_AGENT).strip()
    if key in specs:
        return specs[key]
    logger.info("agent_type %s 未注册，回落 %s", key, FALLBACK_AGENT)
    return specs[FALLBACK_AGENT]
