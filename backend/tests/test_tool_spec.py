"""ToolSpec 契约测试（v2.2.0-p1.1 / Phase A2）——判据载体。

判据（PLAN-2.2.0 A2）：registry 能枚举全部工具及其权限/幂等元数据；
默认注册表零漏标注；白名单裁剪不丢元数据；非幂等副作用工具的重试
必须在日志里可见（可观测不改行为）。
"""
import logging

import pytest

from app.orchestration.agents import build_default_registry, build_registry_for_spec
from app.orchestration.tools import ToolRegistry, ToolSpec


def _default_registry() -> ToolRegistry:
    return build_default_registry(None)


def test_every_tool_has_explicit_spec():
    """判据主用例：默认注册表 13 个工具全部显式批注，无漏网（漏标注=测试红）。"""
    reg = _default_registry()
    assert reg.unannotated() == []
    assert len(reg.names()) == 13
    assert set(reg.specs()) == set(reg.names())


def test_read_tools_are_side_effect_free():
    reg = _default_registry()
    for name in ("query_orders", "compare_orders", "sales_report", "db_query", "analyze_table", "read_document", "rag_retrieve"):
        spec = reg.spec_of(name)
        assert spec.side_effect is False, name
        assert spec.idempotent is True, name


def test_write_tools_declare_side_effect():
    reg = _default_registry()
    for name in ("clean_table", "export_orders", "render_chart", "render_flow", "write_document", "ask_user"):
        assert reg.spec_of(name).side_effect is True, name


def test_write_document_is_the_non_idempotent_one():
    """生成式写文档：重试=重烧钱+内容漂移，必须标非幂等（Phase C1 幂等键的靶子）。"""
    reg = _default_registry()
    spec = reg.spec_of("write_document")
    assert spec.idempotent is False
    assert spec.permission == "fs:write"


def test_permission_domains_cover_expected_sets():
    reg = _default_registry()
    specs = reg.specs()
    db_read = {n for n, s in specs.items() if s.permission == "db:read"}
    fs_write = {n for n, s in specs.items() if s.permission == "fs:write"}
    assert db_read == {"query_orders", "compare_orders", "sales_report", "db_query"}
    assert "write_document" in fs_write and "export_orders" in fs_write


def test_unannotated_tool_falls_back_to_pessimistic_spec():
    """漏标注兜底：悲观档（side_effect=True / idempotent=False），unannotated 可查。"""
    reg = ToolRegistry()
    reg.register("mystery", lambda: "x", description="未批注")
    assert reg.unannotated() == ["mystery"]
    spec = reg.spec_of("mystery")
    assert spec.side_effect is True and spec.idempotent is False


def test_spec_survives_whitelist_copy():
    """build_registry_for_spec 的白名单裁剪不丢元数据（copy_into 搬运）。"""
    base = _default_registry()
    sub = build_registry_for_spec(
        type("S", (), {"agent_type": "t", "tools": ["query_orders", "write_document"]})(),
        base,
    )
    assert sub.spec_of("query_orders").side_effect is False
    assert sub.spec_of("write_document").idempotent is False
    assert sub.unannotated() == []


def test_set_spec_rejects_unknown_tool():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.set_spec("ghost", ToolSpec())


def test_non_idempotent_retry_logs_warning(caplog):
    """非幂等副作用工具重试 → WARNING 可见（可观测不改行为；幂等键 Phase C1 落）。"""
    calls = []

    def flaky(v):
        calls.append(v)
        if len(calls) < 2:
            raise RuntimeError("第一次失败")
        return "ok"

    reg = ToolRegistry()
    reg.register("gen", flaky)
    reg.set_spec("gen", ToolSpec(side_effect=True, idempotent=False))
    with caplog.at_level(logging.WARNING, logger="app.orchestration.tools"):
        res = reg.call("gen", v=1, max_retries=1, backoff=0)
    assert res.ok and res.attempts == 2
    assert any("副作用可能重复" in r.message for r in caplog.records)


def test_idempotent_retry_stays_quiet(caplog):
    """幂等工具重试不需要告警（噪声控制）。"""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("第一次失败")
        return "ok"

    reg = ToolRegistry()
    reg.register("q", flaky)
    reg.set_spec("q", ToolSpec(side_effect=False, idempotent=True))
    with caplog.at_level(logging.WARNING, logger="app.orchestration.tools"):
        res = reg.call("q", max_retries=1, backoff=0)
    assert res.ok
    assert not any("副作用可能重复" in r.message for r in caplog.records)
