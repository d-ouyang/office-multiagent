"""业务 Agent 注册表测试（p5.1b）——配置驱动加载 / 回落 / 工具白名单。"""
from app.orchestration.agents import (
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
    assert get_agent_spec("rag_retrieval").tools == ["rag_retrieve", "remember", "recall"]
    assert get_agent_spec("data_analysis").tools == [
        "query_orders", "sales_report", "db_query", "clean_table", "analyze_table",
        "write_document", "render_chart", "remember", "recall",
    ]
    assert get_agent_spec("data_cleaning").tools == ["db_query", "clean_table", "analyze_table"]
    assert get_agent_spec("general").tools == [
        "query_orders", "sales_report", "db_query", "rag_retrieve", "read_document",
        "clean_table", "analyze_table", "write_document", "render_chart", "remember", "recall",
    ]
    assert get_agent_spec("report_generation").tools == [
        "query_orders", "sales_report", "db_query", "rag_retrieve", "read_document",
        "clean_table", "analyze_table", "write_document", "render_chart", "remember", "recall",
    ]


def test_no_tool_agents_declare_empty():
    # visualization / image_restore：工具池暂无对应工具——留空，由 Brain 如实告知能力暂缺
    assert get_agent_spec("visualization").tools == ["clean_table", "render_chart"]
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
