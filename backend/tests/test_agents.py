"""业务 Agent 注册表测试（p5.1b）——配置驱动加载 / 回落 / 工具白名单。"""
from app.orchestration.agents import (
    build_default_registry,
    build_registry_for_spec,
    get_agent_spec,
    load_agent_specs,
)
from app.orchestration.tools import ToolRegistry

_ALL = (
    "general", "rag_retrieval", "data_analysis", "data_cleaning",
    "report_generation", "visualization", "image_restore",
)


def test_specs_loaded_all_seven():
    specs = load_agent_specs()
    for t in _ALL:
        assert t in specs, f"缺 {t}"
        assert specs[t].system_prompt, f"{t} 缺角色提示词"
        assert specs[t].name


def test_spec_tools_whitelist():
    # p6.29：general/rag_retrieval/data_analysis/report_generation 四类挂显式长期记忆工具
    # p6.30：query_orders 系三类加 export_orders（明细导出）
    assert get_agent_spec("rag_retrieval").tools == ["rag_retrieve", "render_flow", "remember", "recall"]
    assert get_agent_spec("data_analysis").tools == [
        "query_orders", "export_orders", "compare_orders", "sales_report", "db_query", "clean_table",
        "analyze_table", "write_document", "render_chart", "render_flow", "remember", "recall",
    ]
    assert get_agent_spec("data_cleaning").tools == ["db_query", "clean_table", "analyze_table"]
    assert get_agent_spec("general").tools == [
        "query_orders", "export_orders", "compare_orders", "sales_report", "db_query", "rag_retrieve", "read_document",
        "clean_table", "analyze_table", "write_document", "render_chart", "render_flow", "remember", "recall",
    ]
    assert get_agent_spec("report_generation").tools == [
        "query_orders", "export_orders", "compare_orders", "sales_report", "db_query", "rag_retrieve", "read_document",
        "clean_table", "analyze_table", "write_document", "render_chart", "render_flow", "remember", "recall",
    ]


def test_no_tool_agents_declare_empty():
    # visualization（p6.46）：补上 query_orders——"按数据库订单统计并画图"走
    # query_orders(group_by)→clean_id→render_chart，不再依赖上传文件作跳板。
    assert get_agent_spec("visualization").tools == ["query_orders", "clean_table", "render_chart"]
    # image_restore：工具池暂无对应工具——留空，由 Brain 如实告知能力暂缺
    assert get_agent_spec("image_restore").tools == []


def test_unknown_agent_falls_back_to_general():
    assert get_agent_spec("no_such_agent").agent_type == "general"
    assert get_agent_spec(None).agent_type == "general"


def test_every_prompt_forbids_fabrication():
    for t in _ALL:
        prompt = get_agent_spec(t).system_prompt
        assert ("编造" in prompt) or ("假装" in prompt), f"{t} 提示词缺'不编造'纪律"


def test_build_registry_for_spec_filters():
    base = ToolRegistry()
    base.register("db_query", lambda: {}, description="查库")
    base.register("rag_retrieve", lambda q: {}, description="检索")
    reg = build_registry_for_spec(get_agent_spec("rag_retrieval"), base)
    assert reg.names() == ["rag_retrieve"]  # 白名单裁剪
    assert reg.describe()[0]["description"] == "检索"


def test_build_registry_skips_unknown_and_empty():
    base = ToolRegistry()
    base.register("db_query", lambda: {}, description="查库")
    assert build_registry_for_spec(get_agent_spec("data_analysis"), base).names() == ["db_query"]
    # visualization tools=[] → 空注册表 → Brain 对其如实告知"无工具"
    assert build_registry_for_spec(get_agent_spec("visualization"), base).names() == []


# ---------- v2.0.0-p1.1：OpenAI tools 导出与 Schema 完整性 ----------

def test_register_schema_normalizes_object():
    reg = ToolRegistry()
    reg.register("t", lambda **kw: kw, description="d", parameters={"properties": {"a": {"type": "string"}}})
    schema = reg.schema_of("t")
    assert schema is not None
    assert schema["type"] == "object" and schema["additionalProperties"] is False


def test_register_rejects_non_dict_schema():
    import pytest
    reg = ToolRegistry()
    with pytest.raises(ValueError):
        reg.register("t", lambda **kw: kw, parameters=["bad"])  # type: ignore[arg-type]


def test_describe_openai_excludes_schema_incomplete():
    reg = ToolRegistry()
    reg.register("ready", lambda **kw: kw, description="完整", parameters={"properties": {"q": {"type": "string"}}})
    reg.register("raw", lambda **kw: kw, description="缺 Schema")
    openai_tools = reg.describe_openai()
    assert [t["function"]["name"] for t in openai_tools] == ["ready"]
    fn = openai_tools[0]["function"]
    assert fn["parameters"]["properties"] == {"q": {"type": "string"}}
    assert reg.schema_incomplete() == ["raw"]


def test_build_registry_for_spec_carries_schema():
    base = ToolRegistry()
    base.register("db_query", lambda **kw: kw, description="查库", parameters={"properties": {"sql": {"type": "string"}}})
    reg = build_registry_for_spec(get_agent_spec("data_cleaning"), base)
    assert reg.schema_of("db_query") is not None
    assert [t["function"]["name"] for t in reg.describe_openai()] == ["db_query"]


def test_default_registry_tools_all_have_schema():
    reg = build_default_registry(engine=None)
    assert reg.names()
    assert reg.schema_incomplete() == [], f"缺 Schema 的工具：{reg.schema_incomplete()}"
    for tool in reg.describe_openai():
        fn = tool["function"]
        assert tool["type"] == "function" and fn["parameters"]["type"] == "object"
