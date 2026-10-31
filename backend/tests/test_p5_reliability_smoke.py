"""p5 可靠性加固 · 链路级冒烟（故障注入，不需要真实 LLM key、不访问外网）。

与单测的区别：单测只验证 `llm.py` / `tools.py` 孤立函数；本文件把故障注入到
**真实执行链路**上——brain → llm.chat（含重试）→ run_react / run_dag，
验证"重试之后任务到底能不能跑完、会不会重复输出、降级是否如实"。

故障用 `httpx.MockTransport` 制造，因为 429/500 无法靠手动操作稳定复现。
"""
import httpx
import pytest

from app.core import llm as llm_mod
from app.core.config import settings
from app.core.events import RunEventEmitter
from app.orchestration.brain import LlmBrain, make_brain
from app.orchestration.react import run_react
from app.orchestration.tools import ToolRegistry

_MODEL = "deepseek-chat"


@pytest.fixture(autouse=True)
def _fast_and_deterministic(monkeypatch):
    """密钥就绪（否则 make_brain 回落 StubBrain）+ 重试退避不真睡，保证快且确定。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_max_retries", 2)
    monkeypatch.setattr("app.core.llm.time.sleep", lambda _s: None)


def _chat_fn(handler):
    """注入到 brain 的 chat_fn：仍走真实 llm.chat（含重试），只把传输层换成 Mock。"""
    transport = httpx.MockTransport(handler)

    def _chat(model_id, messages, **kwargs):
        return llm_mod.chat(model_id, messages, transport=transport, **kwargs)

    return _chat


def _sse(lines):
    body = "".join(f"data: {line}\n\n" for line in lines).encode()
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def _ok(content):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 7}},
    )


# --------------------------------------------------------------------------- #
# 1. 429 限流：重试之后整个 ReAct 任务要能跑完，而不是降级成"模型暂不可用"
# --------------------------------------------------------------------------- #
def test_react_completes_after_429_retries():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, json={"error": "rate limited"})
        return _ok('{"thought":"已拿到数据","final":"本季度销售额为 120 万元"}')

    brain = make_brain(ToolRegistry(), chat_fn=_chat_fn(handler), model_id=_MODEL, protocol="json")
    assert isinstance(brain, LlmBrain)  # 确认没回落 StubBrain（否则测试无效）

    res = run_react("本季度销售额是多少", brain, ToolRegistry(), emitter=RunEventEmitter("r", "t"))

    assert res.final == "本季度销售额为 120 万元"
    assert res.hit_cap is False
    assert calls["n"] == 3  # 429 两次 + 成功一次
    assert brain.usage["total_tokens"] == 7  # 只累计成功那次，重试不重复计账
    assert brain.usage["calls"] == 1


# --------------------------------------------------------------------------- #
# 2. 持续 500：重试耗尽后必须如实降级，不能编造答案
# --------------------------------------------------------------------------- #
def test_react_degrades_honestly_when_retries_exhausted():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(500, json={"error": "internal"})

    brain = make_brain(ToolRegistry(), chat_fn=_chat_fn(handler), model_id=_MODEL, protocol="json")
    res = run_react("随便一个任务", brain, ToolRegistry(), emitter=RunEventEmitter("r", "t"))

    assert "模型暂不可用" in res.final  # 如实告知，不硬编答案
    assert calls["n"] == 3  # 1 次原始 + 2 次重试，耗尽即停
    assert brain.usage["total_tokens"] == 0  # 没成功就没有用量


# --------------------------------------------------------------------------- #
# 3. 流式路径：首块前 429 可重试，且用户不会看到重复正文
# --------------------------------------------------------------------------- #
def test_streaming_recovers_from_429_without_duplicate_content():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return _sse(['{"choices":[{"delta":{"content":"你好"}}]}',
                     '{"choices":[{"delta":{"content":"，世界"}}]}', "[DONE]"])

    transport = httpx.MockTransport(handler)

    def _chat_stream(model_id, messages, **kwargs):
        return llm_mod.chat_stream(model_id, messages, transport=transport, **kwargs)

    pushed: list[str] = []
    brain = LlmBrain(
        model_id=_MODEL, tools=ToolRegistry(), chat_stream_fn=_chat_stream,
        stream=True, on_content=pushed.append, protocol="json",
    )
    res = run_react("打个招呼", brain, ToolRegistry(), emitter=RunEventEmitter("r", "t"))

    assert calls["n"] == 2
    assert res.final == "你好，世界"
    assert "".join(pushed) == "你好，世界"  # 重试没有把开头再推一遍
    assert len(pushed) == 2


# --------------------------------------------------------------------------- #
# 4. 工具级退避在 ReAct 循环内真实生效：第一次失败、退避后第二次成功
# --------------------------------------------------------------------------- #
def test_tool_retry_backoff_applies_inside_react_loop(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("app.orchestration.tools.time.sleep", sleeps.append)
    monkeypatch.setattr(settings, "tool_retry_backoff", 0.4)

    tools = ToolRegistry()
    state = {"n": 0}

    def flaky_query():
        state["n"] += 1
        if state["n"] == 1:
            raise ConnectionError("DB 连接被重置")
        return {"rows": [{"amount": 120}], "note": "重试后拿到数据"}

    tools.register("query_orders", flaky_query)
    responses = iter([
        '{"thought":"需要查订单","action":"query_orders","action_input":{}}',
        '{"thought":"拿到数据","final":"销售额 120 万元"}',
    ])

    def handler(req):
        return _ok(next(responses))

    brain = make_brain(tools, chat_fn=_chat_fn(handler), model_id=_MODEL, protocol="json")
    res = run_react("查销售额", brain, tools, emitter=RunEventEmitter("r", "t"))

    assert res.final == "销售额 120 万元"
    assert state["n"] == 2          # 工具第二次才成功
    # 第一次 sleep 就是工具退避；后续的 0.012 是 chunked 终答的切片推送间隔（react.py）
    assert sleeps[0] == 0.4         # 退避真的发生了（此前恒为 0，立即重试）
    assert any("重试后拿到数据" in (s.observation or "") for s in res.steps)
