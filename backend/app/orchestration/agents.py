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
from typing import Any

import yaml
from sqlalchemy.engine import Engine

from ..core.config import settings
from .tools import ToolRegistry
from .tools_db import make_db_query_tool
from .tools_compare import make_compare_orders_tool
from .tools_export import make_export_orders_tool
from .tools_flow import render_flow
from .tools_orders import make_query_orders_tool
from .tools_report import make_sales_report_tool
from .tools_chart import make_render_chart_tool
from .tools_doc import make_read_document_tool
from .tools_rag import make_rag_retrieve_tool
from .tools_table import make_analyze_table_tool, make_clean_table_tool
from .tools_write import make_write_document_tool

logger = logging.getLogger(__name__)

FALLBACK_AGENT = "general"

# v2.0.0-p1.1：OpenAI function calling 参数 Schema（与工具实现 kwargs 一一对应）。
# 白名单/描述仍以 agents.yaml 为准，这里只补 tool_calls 模式所需的 JSON Schema。
_ORDER_FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "column": {"type": "string", "description": "订单表列名"},
        "op": {"type": "string", "enum": ["eq", "ne", "contains", "gt", "gte", "lt", "lte", "in", "not_in"]},
        "value": {},
    },
    "required": ["column", "op", "value"],
    "additionalProperties": False,
}
_ORDER_OPTIONAL = {
    "date_from": {"type": "string", "description": "起始日期 YYYY-MM-DD，按下单时间"},
    "date_to": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
    "store_name": {"type": "string", "description": "门店名，包含匹配"},
    "city": {"type": "string", "description": "城市，按门店地址包含匹配"},
    "order_status": {"type": ["string", "array"], "items": {"type": "string"}, "description": "订单状态，可单个或列表"},
    "exclude_status": {"type": ["string", "array"], "items": {"type": "string"}, "description": "要排除的订单状态"},
    "order_channel": {"type": ["string", "array"], "items": {"type": "string"}},
    "order_type": {"type": ["string", "array"], "items": {"type": "string"}},
    "fulfillment_type": {"type": ["string", "array"], "items": {"type": "string"}},
    "member_level": {"type": ["string", "array"], "items": {"type": "string"}},
    "filters": {"type": "array", "items": _ORDER_FILTER_SCHEMA},
}
_METRIC_ENUM = [
    "count", "sum_pay", "sum_total", "sum_discount", "sum_refund", "avg_pay",
    "sum_goods", "sum_goods_amount", "sum_delivery_fee", "sum_packing_fee",
    "sum_coupon", "sum_points",
]
_ORDER_METRIC = {
    "metric": {"type": "string", "enum": _METRIC_ENUM, "description": "聚合指标"},
    "group_by": {"type": "string", "description": "month、city 或订单表字段"},
}


def _params(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


@dataclass(frozen=True)
class AgentSpec:
    agent_type: str
    name: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 工具池（全部真实工具；各 Agent 按白名单取子集）
# --------------------------------------------------------------------------- #
def build_default_registry(
    engine: Engine | None,
    username: str | None = None,
    user_id: int | None = None,
    task_id: str | None = None,
) -> ToolRegistry:
    reg = ToolRegistry()
    # p6.46：doc_base 提前计算——query_orders 的分组副本要存进同一个 _clean 目录
    owner = (username or "").strip().strip("/") or None
    doc_base = str(Path(settings.documents_dir) / owner) if owner else settings.documents_dir
    reg.register(
        "db_query",
        make_db_query_tool(engine, max_rows=settings.db_query_max_rows),
        description=(
            "查询公司业务库（只读兜底）。锅圈订单不要用它，用 query_orders。"
            "没有专用查询工具时才用。参数 sql：单条 SELECT。必须带 WHERE、GROUP BY 或聚合；"
            "最多返回 50 行，执行超过 3 秒会被数据库打断。禁止写操作。上传的表先 clean_table。"
        ),
        parameters=_params(
            {"sql": {"type": "string", "description": "单条只读 SELECT，必须带 WHERE、GROUP BY 或聚合"}},
            ["sql"],
        ),
    )
    reg.register(
        "query_orders",
        make_query_orders_tool(engine, max_rows=settings.db_query_max_rows, base_dir=str(doc_base)),
        description=(
            "查询已入库的锅圈食汇订单。不要写 SQL，也不要读订单 CSV。"
            "至少要带一个条件：date_from、date_to（YYYY-MM-DD，按下单时间）、"
            "order_no、store_name（包含匹配）、city、order_status、order_channel、"
            "order_type、fulfillment_type、member_level、group_by，或 filters。"
            "city 按门店地址包含匹配：传「上海」或「上海市」都能命中，不限制城市名单。"
            "状态、渠道、类型、履约方式、会员等级按表里的实际值相等匹配，可传一个值或列表，"
            "不要用写死的可选值；表里没有该值时结果就是 0 行。"
            "filters：[{column, op, value}]，column 用订单表列名，"
            "op 取 eq、ne、contains、gt、gte、lt、lte、in、not_in。"
            "多个状态可传列表，或用顿号/逗号分隔；排除用 exclude_status，同样可传多个。"
            "group_by：month、city，或除手机号、真实姓名、收货地址外的任意订单表字段。"
            "city 分组从门店地址取城市名（上海市→上海，河南省郑州市→郑州）。"
            "分组时 metric 默认 sum_pay，还可取 count、sum_total、sum_discount、sum_refund、"
            "avg_pay、sum_goods、sum_goods_amount、sum_delivery_fee、sum_packing_fee、sum_coupon、sum_points。"
            "columns：可选，指定要返回的列名；不传用默认列。limit 最大 50。"
            "不返回手机号、真实姓名和收货地址。"
            "不要某状态时传 exclude_status，例如不要退款就传 已退款。"
            "字段名对不上时会说明没有这个字段。某个取值在表里不存在时返回 0 行，不要改去猜列名或改用 db_query。"
            "同比、环比、占比不要自己算，改用 compare_orders。"
            "销售报表不要用本工具拼结论，改用 sales_report。"
            "【要订单明细表格/导出文件时不要用本工具，改用 export_orders】。"
            "分组统计会同时返回 clean_id（可分析副本）：要画图或再分析时直接把它交给 "
            "render_chart（x=grp，y=metric_value 或 order_count）/ analyze_table，"
            "绝不调用 clean_table 去读一个不存在的文件。"
        ),
        parameters=_params(
            {
                "order_no": {"type": "string", "description": "按订单号精确查"},
                **_ORDER_OPTIONAL,
                **_ORDER_METRIC,
                "columns": {"type": "array", "items": {"type": "string"}, "description": "可选返回列"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        ),
    )
    reg.register(
        "sales_report",
        make_sales_report_tool(engine),
        description=(
            "生成锅圈销售报表。数字只来自 query_orders，不要自己计算或改写。"
            "必填 date_from、date_to（YYYY-MM-DD）和 metric。"
            "metric：count、sum_pay、sum_total、sum_discount、sum_refund、avg_pay、sum_goods、"
            "sum_goods_amount、sum_delivery_fee、sum_packing_fee、sum_coupon、sum_points。"
            "可选 city（按门店地址匹配，不限城市）、store_name、order_status、exclude_status、order_channel、order_type、"
            "fulfillment_type、member_level、group_by。用户说只要某城市、不要某状态时，必须传对应参数。"
            "时间范围、指标、口径、数据来源缺任何一项时 complete 为 false，这时不能说报表已完成。"
            "complete 为 true 时，report 就是报表正文。下一步直接分析并给销售建议，不要再次调用本工具，也不要再读文件。"
            "同比、环比、占比用 compare_orders，不要拿报表数字自己除。"
        ),
        parameters=_params(
            {
                "date_from": _ORDER_OPTIONAL["date_from"],
                "date_to": _ORDER_OPTIONAL["date_to"],
                "metric": _ORDER_METRIC["metric"],
                **{k: v for k, v in _ORDER_OPTIONAL.items() if k not in ("date_from", "date_to")},
            },
            ["date_from", "date_to", "metric"],
        ),
    )
    reg.register(
        "rag_retrieve",
        make_rag_retrieve_tool(
            base_url=settings.rag_base_url,
            internal_secret=settings.rag_internal_secret,
            username=settings.rag_service_username,
            # 知识库账号仍用服务号，避免办公用户在 RAG 用户表里不存在时整段检索 401。
            # 返回里带上真实办公用户，管理端据此标红身份不一致。
            actor=username,
        ),
        description=(
            "检索公司知识库（制度/文档问答）。参数 query。走知识库完整链路，但不写入知识库会话。"
            "返回 answer、sources（含 rerank_score 重排分）、grounded（依据是否站住）。"
            "回答必须转述这些字段，不要编造出处。usage 已计入本轮消耗。"
        ),
        parameters=_params({"query": {"type": "string", "description": "检索问题"}}, ["query"]),
    )
    owner = (username or "").strip().strip("/") or None
    doc_base = str(Path(settings.documents_dir) / owner) if owner else settings.documents_dir
    if owner:
        read_desc = (
            "读取当前登录用户上传目录中的文件（支持 .md/.txt/.json/.csv/.docx/.xlsx/.pdf/.png/.jpg/.webp）。"
            "PDF 有文字层就直接抽文字。没有文字层的扫描件，以及图片，会转成文字后再返回。"
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
        parameters=_params(
            {"file_name": {"type": "string", "description": "上传目录内的文件名（或 用户名/文件名）"}},
            ["file_name"],
        ),
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
        parameters=_params(
            {
                "file_name": {"type": "string", "description": "上传目录内的文件名"},
                "key_columns": {"type": "array", "items": {"type": "string"}, "description": "关键列，这些列为空的行剔除"},
                "sheet": {"type": "string", "description": "xlsx 工作表名"},
            },
            ["file_name"],
        ),
    )
    reg.register(
        "analyze_table",
        make_analyze_table_tool(base_dir=doc_base, owner=owner),
        description=(
            "只分析 clean_table 返回的表。参数 clean_id 必填，不能传原始文件名。"
            "group_by：分组列，可空。metrics：[{column, agg}]，agg 取 count、sum、mean、min、max、count_distinct；"
            "不传 metrics 时只计数。filters：[{column, op, value}]，op 取 eq、ne、contains、gt、gte、lt、lte、in、not_in"
            "（in/not_in 的 value 可传列表，用于从分组结果里挑特定值，如只取 9 月和 10 月）。"
            "sum/mean/min/max 遇到不能转成数字的格子会跳过并计数，不会当成 0。"
        ),
        parameters=_params(
            {
                "clean_id": {"type": "string", "description": "clean_table 返回的 id"},
                "group_by": {"type": ["string", "array"], "items": {"type": "string"}},
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "agg": {"type": "string", "enum": ["count", "sum", "mean", "min", "max", "count_distinct"]},
                        },
                        "required": ["column", "agg"],
                        "additionalProperties": False,
                    },
                },
                "filters": {"type": "array", "items": _ORDER_FILTER_SCHEMA},
            },
            ["clean_id"],
        ),
    )
    reg.register(
        "export_orders",
        make_export_orders_tool(
            engine,
            base_dir=str(doc_base),
            owner=owner,
            user_id=user_id,
            task_id=task_id,
        ),
        description=(
            "导出订单明细表格文件（csv 或 xlsx），是「形成表格/导出明细」类请求的正解。"
            "必填 date_from、date_to（YYYY-MM-DD）。可选 city（按门店地址包含匹配，不限城市）、"
            "store_name、order_status、exclude_status、order_channel、order_type、fulfillment_type、"
            "member_level（均可传一个值或列表）、filters（同 query_orders，按订单表任意字段筛选）、"
            "fields（中文列名或订单表列名，如 [销售金额, 门店, 用户, 是否线上, 平台, 门店地址, pay_time]）、"
            "format（csv/xlsx）。字段映射规则：手机号自动脱敏进文件；「是否线上」由渠道推导"
            "（门店扫码→线下，其余→线上）；表里没有的字段（如支付方式）【整列省略】并在返回的 "
            "omitted 里说明，绝不编造该列。返回 export_id 和 file_name：可直接交给 render_chart "
            "画图（不必再 clean_table），也可作为交付物告知用户预览/下载。"
            "【要画时间趋势图时，fields 必须包含「下单时间」列，否则画不了按月趋势】。"
        ),
        parameters=_params(
            {
                "date_from": _ORDER_OPTIONAL["date_from"],
                "date_to": _ORDER_OPTIONAL["date_to"],
                "city": _ORDER_OPTIONAL["city"],
                "store_name": _ORDER_OPTIONAL["store_name"],
                "order_status": _ORDER_OPTIONAL["order_status"],
                "exclude_status": _ORDER_OPTIONAL["exclude_status"],
                "order_channel": _ORDER_OPTIONAL["order_channel"],
                "order_type": _ORDER_OPTIONAL["order_type"],
                "fulfillment_type": _ORDER_OPTIONAL["fulfillment_type"],
                "member_level": _ORDER_OPTIONAL["member_level"],
                "filters": _ORDER_OPTIONAL["filters"],
                "fields": {"type": "array", "items": {"type": "string"}, "description": "导出列（中文列名或订单表列名）"},
                "format": {"type": "string", "enum": ["csv", "xlsx"]},
            },
            ["date_from", "date_to"],
        ),
    )
    reg.register(
        "write_document",
        make_write_document_tool(
            base_dir=doc_base, owner=owner, engine=engine, user_id=user_id, task_id=task_id
        ),
        description=(
            "把已经得到的结论写成 md、docx、pdf 或 pptx，不画数据图，也不生成 xlsx。"
            "参数 title：标题。content：正文，数字必须来自此前的工具结果。"
            "format：md、docx、pdf、pptx。用户要演示文稿用 pptx，要发出去的成稿用 pdf。"
            "clean_id：若结论来自清洗后的表，传入它，文末会写上来源和行数。"
            "image_file：要把图表嵌进文档时，传 render_chart 返回的 png_file（文档内会嵌入该图）。"
            "返回 file_name。失败就说明没生成，不要给一个不存在的下载地址。"
        ),
        parameters=_params(
            {
                "title": {"type": "string", "description": "文档标题"},
                "content": {"type": "string", "description": "正文，数字必须来自此前工具结果"},
                "format": {"type": "string", "enum": ["md", "docx", "pdf", "pptx"]},
                "clean_id": {"type": "string", "description": "结论来自清洗表时传，用于文末标注来源"},
                "image_file": {"type": "string", "description": "render_chart 返回的 png_file，嵌入文档"},
            },
            ["title", "content", "format"],
        ),
    )
    reg.register(
        "render_chart",
        make_render_chart_tool(
            base_dir=doc_base, owner=owner, engine=engine, user_id=user_id, task_id=task_id
        ),
        description=(
            "根据表格数据画图，数字只来自那张表。不能自己传数据点。"
            "第一个参数传 clean_id（clean_table 产物，c- 开头）或 export_id（export_orders 产物，e- 开头）"
            "——订单明细导出后可直接画图，不必再 clean_table。"
            "chart：bar、barh、line、area、pie、scatter、heatmap、hist。"
            "x：分类列；折线/面积按 x 排序，柱状按汇总值取前 top_n 个。"
            "y：数值列，可传一个或列表。agg：sum、mean、count、min、max，默认 sum。"
            "series：分组列，和多个 y 不能同时用。heatmap 必须有 x、series 和 y。"
            "scatter 的 x、y 都是数字列。hist 用 y 或 x 做分箱，bins 默认 10。"
            "filters 与 analyze_table 相同。饼图超过 8 类会把其余并成「其他」，且不能有负数。"
            "返回 visual（界面用 ECharts 画）以及 svg/png 文件（供下载和嵌进文档）。"
        ),
        parameters=_params(
            {
                "clean_id": {"type": "string", "description": "clean_id（c- 开头）或 export_id（e- 开头）"},
                "chart": {"type": "string", "enum": ["bar", "barh", "line", "area", "pie", "scatter", "heatmap", "hist"]},
                "x": {"type": "string", "description": "分类列"},
                "y": {"type": ["string", "array"], "items": {"type": "string"}, "description": "数值列，可一个或列表"},
                "series": {"type": "string", "description": "分组列，与多个 y 互斥"},
                "agg": {"type": "string", "enum": ["sum", "mean", "count", "min", "max"]},
                "title": {"type": "string"},
                "filters": {"type": "array", "items": _ORDER_FILTER_SCHEMA},
                "top_n": {"type": "integer", "minimum": 1},
                "bins": {"type": "integer", "minimum": 2},
            },
            ["clean_id", "chart", "x"],
        ),
    )
    reg.register(
        "render_flow",
        render_flow,
        description=(
            "画流程图，供界面在回答过程中渲染。不要自己输出 SVG 或坐标。"
            "参数 title。nodes：[{id, label, kind, lane}]，kind 为 rect 或 diamond，"
            "lane 取 blue、purple、teal、amber、green、red、gray。"
            "edges：[{from, to, label}]。path：实走节点 id 列表，按顺序。"
            "判断用 diamond，其余用 rect。没走到的分支不要放进 path，只放在 edges 里。"
        ),
        parameters=_params(
            {
                "title": {"type": "string"},
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "kind": {"type": "string", "enum": ["rect", "diamond"]},
                            "lane": {"type": "string", "enum": ["blue", "purple", "teal", "amber", "green", "red", "gray"]},
                        },
                        "required": ["id", "label", "kind", "lane"],
                        "additionalProperties": False,
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"from": {"type": "string"}, "to": {"type": "string"}, "label": {"type": "string"}},
                        "required": ["from", "to"],
                        "additionalProperties": False,
                    },
                },
                "path": {"type": "array", "items": {"type": "string"}},
            },
        ),
    )
    reg.register(
        "compare_orders",
        make_compare_orders_tool(engine),
        description=(
            "计算订单的环比、同比或占比。数字只来自 query_orders，变化率由代码计算。"
            "必填 date_from、date_to、metric（与 query_orders 相同）。"
            "mode：mom 环比（紧挨着的上一段等长时间）、yoy 同比（去年同期）、share 占比。"
            "share 必须带 group_by。其余筛选参数与 query_orders 相同。"
            "ratio 为空表示上期为 0，不要自己编一个百分比。"
        ),
        parameters=_params(
            {
                "date_from": _ORDER_OPTIONAL["date_from"],
                "date_to": _ORDER_OPTIONAL["date_to"],
                "metric": _ORDER_METRIC["metric"],
                "mode": {"type": "string", "enum": ["mom", "yoy", "share"]},
                **{k: v for k, v in _ORDER_OPTIONAL.items() if k not in ("date_from", "date_to")},
            },
            ["date_from", "date_to", "metric", "mode"],
        ),
    )
    # p6.29：显式长期记忆（仅登录用户场景挂载；匿名=无记忆能力，工具不可见）
    if user_id is not None:
        from .tools_memory import register_memory_tools
        from ..core.user_memory_repo import UserMemoryRepo

        register_memory_tools(reg, UserMemoryRepo(engine), int(user_id))
    return reg


def build_registry_for_spec(spec: AgentSpec, base: ToolRegistry) -> ToolRegistry:
    """按 AgentSpec 的工具白名单裁剪；白名单里的未知名记 warning（对 Agent 不可见=能力缺失）。"""
    reg = ToolRegistry()
    for name in spec.tools:
        if not base.has(name):
            logger.warning("Agent %s 声明了未注册工具 %s（跳过=对该 Agent 能力缺失）", spec.agent_type, name)
            continue
        base.copy_into(reg, name)
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
