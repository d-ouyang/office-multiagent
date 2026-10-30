"""工具层 + 兜底测试（p4.1，§四.5）。"""
from app.orchestration.tools import ToolRegistry


def test_call_success():
    reg = ToolRegistry()
    reg.register("echo", lambda x: f"echo:{x}")
    r = reg.call("echo", x="hi")
    assert r.ok and r.output == "echo:hi" and r.attempts == 1


def test_retry_then_success():
    reg = ToolRegistry()
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise ValueError("boom")
        return "ok"

    reg.register("flaky", flaky)
    r = reg.call("flaky", max_retries=2, backoff=0)
    assert r.ok and r.output == "ok" and r.attempts == 3


def test_retry_exhausted_returns_error():
    reg = ToolRegistry()

    def always():
        raise RuntimeError("down")

    reg.register("bad", always)
    r = reg.call("bad", max_retries=2, backoff=0)
    assert not r.ok and r.attempts == 3 and "down" in r.error


def test_missing_tool_capability_missing_not_fabricate():
    reg = ToolRegistry()
    r = reg.call("nope")
    assert not r.ok
    assert r.error.startswith("CAPABILITY_MISSING")  # 如实告知，不胡编
    assert r.attempts == 0


# ---------- p5.3：工具级重试退避生效 ----------
def test_default_backoff_read_from_settings(monkeypatch):
    """缺省退避不再恒为 0——瞬时抖动（DB/对端限流）需要真正等一等再重试。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "tool_retry_backoff", 0.5)
    sleeps: list[float] = []
    monkeypatch.setattr("app.orchestration.tools.time.sleep", sleeps.append)
    reg = ToolRegistry()
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            raise ValueError("transient")
        return "ok"

    reg.register("flaky", flaky)
    r = reg.call("flaky")  # 不传 backoff：走配置缺省
    assert r.ok and r.attempts == 2
    assert sleeps == [0.5]


def test_backoff_grows_with_attempt(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "tool_retry_backoff", 0.2)
    sleeps: list[float] = []
    monkeypatch.setattr("app.orchestration.tools.time.sleep", sleeps.append)
    reg = ToolRegistry()

    def always():
        raise RuntimeError("down")

    reg.register("bad", always)
    r = reg.call("bad", max_retries=2)
    assert not r.ok and r.attempts == 3
    assert sleeps == [0.2, 0.4]  # 线性退避：base × attempt


def test_explicit_backoff_zero_disables_sleep(monkeypatch):
    """显式 backoff=0 仍是「立即重试」，既有测试与调用方语义不变。"""
    sleeps: list[float] = []
    monkeypatch.setattr("app.orchestration.tools.time.sleep", sleeps.append)
    reg = ToolRegistry()
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            raise ValueError("x")
        return "ok"

    reg.register("flaky", flaky)
    r = reg.call("flaky", backoff=0)
    assert r.ok and r.attempts == 2
    assert sleeps == []
