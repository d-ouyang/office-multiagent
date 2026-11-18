"""ModelAdapter 契约测试（v2.2.0-p1.0 / Phase A1）——A1 完成判据的载体。

判据（PLAN-2.2.0 A1）：注入 FakeModelAdapter 后，
brain/react 全链路不改调用点、不出网、不依赖 MockTransport 即可跑通。
"""
import pytest

from app.core import llm
from app.core.events import RunEventEmitter
from app.core.llm import LlmResult, ToolCall
from app.core.model_adapter import (
    FakeModelAdapter,
    OpenAICompatAdapter,
    get_adapter,
    reset_adapter,
    set_adapter,
)
from app.orchestration.brain import LlmBrain
from app.orchestration.react import run_react
from app.orchestration.tools import ToolRegistry


@pytest.fixture(autouse=True)
def _reset_adapter_after_each_test():
    """Fake 是进程级全局注入：用例结束必须还原，否则跨用例泄漏假模型。"""
    yield
    reset_adapter()


def test_facade_forwards_to_injected_fake():
    """门面转发：set_adapter 后 llm.chat 不出网、返回脚本结果。"""
    fake = set_adapter(FakeModelAdapter([LlmResult(content="fake-ok", total_tokens=7)]))
    res = llm.chat("whatever-model", [{"role": "user", "content": "hi"}])
    assert res.content == "fake-ok"
    assert fake.calls[0]["model_id"] == "whatever-model"


def test_chat_stream_facade_uses_fake_too():
    fake = set_adapter(FakeModelAdapter(["流式终值"]))
    res = llm.chat_stream("m", [{"role": "user", "content": "hi"}])
    assert res.content == "流式终值"  # str script 自动包装为 LlmResult


def test_script_advances_and_exhaustion_is_loud():
    """脚本逐次弹出；耗尽再调用必须炸（模型多调一轮 = 循环 bug，不能静默）。"""
    fake = set_adapter(FakeModelAdapter(["第一轮", "第二轮"]))
    assert llm.chat("m", [{"role": "user", "content": "a"}]).content == "第一轮"
    assert llm.chat("m", [{"role": "user", "content": "b"}]).content == "第二轮"
    assert len(fake.calls) == 2
    with pytest.raises(AssertionError, match="脚本耗尽"):
        llm.chat("m", [{"role": "user", "content": "c"}])


def test_callable_script_branches_on_messages():
    """callable 按入参分支：第一轮给工具调用 JSON，第二轮给终答。"""

    def decide(model_id, messages, **kwargs):
        # JSON 协议下历史拼进单条 user 消息（messages 恒为 [system, user]）：
        # 第二轮的 user 里会出现上一轮的 action=echo，以它区分第几轮最可靠。
        user_content = messages[-1].get("content", "") if messages else ""
        if "echo" in user_content:
            return '{"thought":"完成","final":"结论 42"}'
        return '{"thought":"先查","action":"echo","action_input":{"x":1}}'

    fake = set_adapter(FakeModelAdapter([decide, decide]))
    reg = ToolRegistry()
    reg.register("echo", lambda x: "观察：echo 结果")
    brain = LlmBrain(model_id="deepseek-chat", tools=reg)
    res = run_react("任务", brain, reg, emitter=RunEventEmitter("r", "t"))
    assert res.final == "结论 42"
    assert res.iterations == 2
    assert len(fake.calls) == 2  # 恰好两轮，没多调


def test_react_end_to_end_with_fake_adapter():
    """A1 判据主用例：Fake 注入 → 真 LlmBrain（默认 chat_fn 门面）→ run_react 全链路。

    无 MockTransport、无真实网络、无密钥：证明「换实现不改调用点」。
    """
    set_adapter(
        FakeModelAdapter(
            [
                '{"thought":"查一下","action":"echo","action_input":{"x":1}}',
                '{"thought":"完成","final":"答案是 5"}',
            ]
        )
    )
    reg = ToolRegistry()
    side_effects: list[int] = []
    reg.register("echo", lambda x: side_effects.append(x) or f"观察：{x}")
    brain = LlmBrain(model_id="deepseek-chat", tools=reg)

    res = run_react("任务", brain, reg, emitter=RunEventEmitter("r", "t"), emit=lambda e: None)

    assert res.final == "答案是 5"
    assert res.iterations == 2
    assert side_effects == [1]  # 副作用恰好一次（幂等基线，Phase C 会扩成契约）


def test_reset_restores_default_openai_adapter():
    """reset 后回到 OpenAI 兼容直连（等价重构：默认行为零变化）。"""
    set_adapter(FakeModelAdapter(["x"]))
    reset_adapter()
    assert isinstance(get_adapter(), OpenAICompatAdapter)


def test_default_adapter_delegates_with_transport(monkeypatch):
    """默认 adapter 的委托链路可用 MockTransport 验证（原 test_llm 行为不回归）。"""
    import httpx

    from app.core.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    adapter = OpenAICompatAdapter()
    body = {
        "choices": [{"message": {"content": "pong", "tool_calls": [
            {"id": "c1", "function": {"name": "t", "arguments": "{}"}}
        ]}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    res = adapter.chat(
        "deepseek-chat",
        [{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)),
    )
    assert res.content == "pong"
    assert res.tool_calls == [ToolCall(id="c1", name="t", arguments={}, arguments_raw="{}")]
