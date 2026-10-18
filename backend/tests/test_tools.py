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
