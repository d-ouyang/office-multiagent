"""Skill 能力层（P1）：spec 加载 → prompt 注入 → 受限工具集，三链路验证。

P1 不接入 router，因此这里只验证注册表与能力包自身行为；
fail-closed 与回落语义是重点（未启用不可路由、未知 skill 返回 None）。
"""
from app.orchestration.tools import ToolRegistry
from app.orchestration.tools_write import make_write_document_tool
from app.skills import SkillRegistry, load_skill_registry
from app.skills.base import SkillContext, parse_skill
from app.skills.doc_writing import run as doc_run


def _base_registry() -> ToolRegistry:
    """只放三个假工具，用来验证白名单裁剪。"""
    reg = ToolRegistry()
    reg.register("write_document", lambda **kw: {"file_name": "_out/x.md"}, description="写文档")
    reg.register("render_chart", lambda **kw: {"png_file": "x.png"}, description="画图")
    reg.register("db_query", lambda **kw: {"rows": []}, description="查库")
    return reg


# --------------------------------------------------------------------------- #
# 链路 1：spec 加载
# --------------------------------------------------------------------------- #
def test_doc_writing_spec_loaded():
    reg = load_skill_registry()
    spec = reg.get("doc_writing")
    assert spec is not None, "doc_writing 应能被扫描加载"
    assert spec.title == "文档写作"
    assert "write_document" in spec.tools
    assert spec.enabled is True  # 参考实现显式打开
    assert spec.fallback == "general"
    assert spec.memory.session_read is True
    assert spec.memory.user_longterm is False  # 最小权限


def test_unknown_skill_returns_none():
    reg = load_skill_registry()
    assert reg.get("nope") is None  # 不猜、不编，交给调用方回落


# --------------------------------------------------------------------------- #
# 链路 2：prompt 注入
# --------------------------------------------------------------------------- #
def test_prompt_loaded_for_skill():
    reg = load_skill_registry()
    prompt = reg.prompt_for("doc_writing")
    assert prompt, "prompt.md 应被读进 spec"
    assert "绝不编造" in prompt
    assert reg.prompt_for("nonexistent") == ""  # 未注册 → 空串，不加额外指令


# --------------------------------------------------------------------------- #
# 链路 3：受限工具集
# --------------------------------------------------------------------------- #
def test_restrict_tools_only_exposes_declared():
    reg = load_skill_registry()
    spec = reg.get("doc_writing")
    limited = reg.restrict_tools(_base_registry(), spec)
    assert limited.has("write_document")
    assert limited.has("render_chart")
    assert not limited.has("db_query")  # 未声明 → 对该 skill 不可见
    assert limited.names() == ["render_chart", "write_document"]


def test_unknown_tool_in_spec_is_skipped():
    """spec 声明了没注册的工具：跳过（能力缺失），不炸、不静默通过。"""
    spec = parse_skill({"name": "s", "tools": ["write_document", "no_such_tool"]})
    reg = SkillRegistry({"s": spec})
    limited = reg.restrict_tools(_base_registry(), spec)
    assert limited.names() == ["write_document"]


# --------------------------------------------------------------------------- #
# fail-closed 与匹配
# --------------------------------------------------------------------------- #
def test_disabled_skill_not_routed_but_loaded():
    spec = parse_skill({"name": "s", "triggers": ["写文档"], "enabled": False})
    reg = SkillRegistry({"s": spec})
    assert reg.match("帮我写文档") is None  # 未启用 → 不参与路由
    assert reg.match("帮我写文档", enabled_only=False) is not None  # 但确实已加载


def test_match_by_keyword_and_intent():
    reg = load_skill_registry()
    assert reg.match("帮我写文档").name == "doc_writing"
    assert reg.match("", intent="write_document").name == "doc_writing"
    assert reg.match("今天天气怎么样") is None  # 无命中 → 回落


# --------------------------------------------------------------------------- #
# run.py 护栏与委托
# --------------------------------------------------------------------------- #
def test_run_rejects_bad_input():
    ctx = SkillContext(tools=_base_registry())
    assert doc_run(ctx, title="", content="x")["ok"] is False
    assert doc_run(ctx, title="t", content="")["ok"] is False
    bad = doc_run(ctx, title="t", content="x", format="xlsx")
    assert bad["ok"] is False and "format" in bad["error"]


def test_run_without_tool_reports_capability_missing():
    ctx = SkillContext(tools=ToolRegistry())
    res = doc_run(ctx, title="t", content="x")
    assert res["ok"] is False and "CAPABILITY_MISSING" in res["error"]


def test_run_delegates_to_write_document(tmp_path):
    """端到端：skill 护栏通过后，真实委托给 write_document 落盘。"""
    reg = ToolRegistry()
    reg.register(
        "write_document",
        make_write_document_tool(base_dir=str(tmp_path)),
        description="写文档",
    )
    out = doc_run(
        SkillContext(tools=reg),
        title="季度总结",
        content="## 结论\n- 上海合计 12",
        format="pdf",
    )
    assert out["ok"] is True
    assert out["output"]["file_name"].endswith(".pdf")
    assert (tmp_path / out["output"]["file_name"]).exists()
