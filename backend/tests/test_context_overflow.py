"""v2.3.0-p1.2：上下文超限兜底测试（O-1 ~ O-5）。

覆盖：错误识别 / 不被当瞬时错误重试 / 压缩后重试一次 / 两次都失败给可操作文案。
手法：直接给 LlmBrain 注入 fake chat（第 N 次调用抛或返回），不触网。
"""
from app.core.llm import ContextOverflowError, LlmError, LlmResult, _is_context_overflow, _is_transient
from app.orchestration.brain import LlmBrain
from app.orchestration.react import Step
from app.orchestration.tools import ToolRegistry


class _FakeChat:
    """按脚本返回/抛错的 chat 替身；记录每次调用收到的 messages。"""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.seen: list[list[dict]] = []

    def __call__(self, model_id, messages, **kwargs):
        self.calls += 1
        self.seen.append(messages)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _brain(chat, *, budget=20000, stream=False) -> LlmBrain:
    return LlmBrain(
        model_id="deepseek-chat",
        tools=ToolRegistry(),
        chat_fn=chat,
        chat_stream_fn=chat,
        protocol="json",
        stream=stream,
        history_budget=budget,
    )


def _history(n=6, chars=3000):
    return [
        Step(
            thought=f"第{i}步",
            action="read_document",
            action_input={"path": f"{i}.md"},
            observation="字" * chars,
        )
        for i in range(1, n + 1)
    ]


def test_detect_overflow_400():
    """O-1：各家 provider 的超限措辞都能识别；业务类 400 不误判。"""
    assert _is_context_overflow(
        400, '{"error":{"message":"This model\'s maximum context length is 131072 tokens"}}'
    )
    assert _is_context_overflow(400, '{"error":{"message":"上下文长度超出限制"}}')
    assert _is_context_overflow(413, "context_length_exceeded")
    assert not _is_context_overflow(400, '{"error":{"message":"Invalid api key"}}')
    assert not _is_context_overflow(400, '{"error":{"message":"余额不足"}}')
    assert not _is_context_overflow(500, "context length")  # 5xx 不按溢出处理


def test_overflow_not_retried_as_transient():
    """O-2：溢出不是瞬时错误——重试三次只会更贵，结果一样。"""
    assert _is_transient(ContextOverflowError("上下文超限（400）：…")) is False
    assert _is_transient(LlmError("LLM 返回 429: rate limit")) is True  # 对照组仍可重试


def test_overflow_triggers_one_emergency_compress():
    """O-3：首次溢出 → 压缩历史后重试一次，第二次成功。"""
    ok = LlmResult(content='{"thought":"给答案","final":"已尽力"}')
    chat = _FakeChat([ContextOverflowError("上下文超限（400）：maximum context length"), ok])
    brain = _brain(chat)

    step = brain.next_step("读这 6 份文档并总结", _history())

    assert step.final == "已尽力"
    assert chat.calls == 2
    first, second = chat.seen
    assert len(second[1]["content"]) < len(first[1]["content"])  # 历史确实被压小了


def test_overflow_after_compress_raises_clear_error():
    """O-4：两次都溢出 → 只调 2 次，给用户可操作文案（不甩 provider 原文）。"""
    chat = _FakeChat(
        [
            ContextOverflowError("上下文超限（400）：maximum context length"),
            ContextOverflowError("上下文超限（400）：maximum context length"),
        ]
    )
    brain = _brain(chat)

    step = brain.next_step("读这 6 份文档并总结", _history())

    assert chat.calls == 2  # 不无限循环
    assert step.thought == "上下文超限"
    assert "拆小" in step.final
    assert "maximum context" not in step.final  # 不把 provider 原文丢给用户


def test_overflow_retry_never_inflates_history():
    """O-5：预算本来就不限（0）时，压缩给 4000 而不是继续不限——否则重试等于没压。"""
    ok = LlmResult(content='{"thought":"给答案","final":"ok"}')
    chat = _FakeChat([ContextOverflowError("context length"), ok])
    brain = _brain(chat, budget=0)

    brain.next_step("总结", _history())

    first, second = chat.seen
    assert len(second[1]["content"]) < len(first[1]["content"])
