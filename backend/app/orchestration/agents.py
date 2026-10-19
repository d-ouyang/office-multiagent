"""默认工具注册表（p5.1a）——真实工具的装配处（设计文档 §五 能力池）。

p5.1a 先落两类真实工具（§五.2 首批）：
  · db_query     公司业务库只读查询（硬护栏见 tools_db）
  · rag_retrieve 公司知识库检索（RAG 作为外部工具复用，走内部接口）
文档解析等重工具留 p5.1b；未注册的能力由 ToolRegistry 返回 CAPABILITY_MISSING
（"能力缺失→如实告知"，§四.5，绝不硬编）。
"""
from __future__ import annotations

from sqlalchemy.engine import Engine

from ..core.config import settings
from .tools import ToolRegistry
from .tools_db import make_db_query_tool
from .tools_rag import make_rag_retrieve_tool


def build_default_registry(engine: Engine | None) -> ToolRegistry:
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
    return reg
