"""Brain 测试（p5.1a）——假 chat（不真调云端）；坏输出如实停止，绝不编造。"""
import pytest

from app.core.config import settings
from app.core.llm import LlmError, LlmResult
from app.orchestration.brain import LlmBrain, extract_json, make_brain
from app.orchestration.react import Step, StubBrain
from app.orchestration.tools import ToolRegistry


class FakeChat:
    """同步 + 流式双模假 LLM（不真调云端）。"""

    def __init__(
        self,
        outputs: list[str] | None = None,
        fail: bool = False,
        stream_chunks: list[str] | None = None,
        reasoning_chunks: list[str] | None = None,
        fail_stream: bool = False,
    ):
        self.outputs = list(outputs or [])
        self.fail = fail
        self.stream_chunks = list(stream_chunks or [])
        self.reasoning_chunks = list(reasoning_chunks or [])
        self.fail_stream = fail_stream
        self.calls: list[list[dict]] = []

    def _result(self, content: str, model_id: str) -> LlmResult:
        return LlmResult(
            content=content, prompt_tokens=10, completion_tokens=5, total_tokens=15,
            model=model_id,
        )

    def __call__(self, model_id: str, messages: list[dict], **kw) -> LlmResult:
        self.calls.append(messages)
        if self.fail:
            raise LlmError("模拟断网")
        return self._result(self.outputs.pop(0), model_id)

    def stream(self, model_id: str, messages: list[dict], *, on_chunk=None, on_thought=None, **kw) -> LlmResult:
        self.calls.append(messages)
        if self.fail_stream:
            raise LlmError("模拟流式断网")
        for t in self.reasoning_chunks:
            if on_thought:
                on_thought(t)
        for c in self.stream_chunks:
            if on_chunk:
                on_chunk(c)
        return self._result("".join(self.stream_chunks), model_id)


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("db_query", lambda sql: {}, description="查询业务库")
    reg.register("rag_retrieve", lambda query: {}, description="检索知识库")
    return reg


def test_extract_json_variants():
    assert extract_json('{"a":1}') == {"a": 1}
    assert extract_json('前言```json\n{"a":1}\n```后记') == {"a": 1}
    assert extract_json('模型说：{"a": 1} 完毕') == {"a": 1}
    assert extract_json("完全不是 JSON") is None


def test_llm_brain_action_step():
    chat = FakeChat(['{"thought":"查库","action":"db_query","action_input":{"sql":"SELECT 1"}}'])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.action == "db_query"
    assert step.action_input == {"sql": "SELECT 1"}
    assert step.final is None
    # 提示词里带工具清单（Brain 知道有哪些能力）
    assert "db_query" in chat.calls[0][0]["content"]


def test_llm_brain_final_step():
    chat = FakeChat(['{"thought":"完成","final":"答案是 5 天"}'])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.final == "答案是 5 天"


def test_llm_brain_bad_json_stops_honestly():
    chat = FakeChat(["我觉觉得应该查一下（不是 JSON）"])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.final is not None and "无法解析" in step.final
    assert step.action is None  # 不猜动作、不编数据


def test_llm_brain_llm_error_stops_honestly():
    chat = FakeChat([], fail=True)
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.final is not None and "模型暂不可用" in step.final


def test_llm_brain_usage_accumulates():
    chat = FakeChat([
        '{"thought":"t1","action":"db_query","action_input":{}}',
        '{"thought":"t2","final":"done"}',
    ])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    brain.next_step("任务", [])
    brain.next_step("任务", [Step(thought="t1", action="db_query", observation="{}")])
    assert brain.usage["calls"] == 2
    assert brain.usage["total_tokens"] == 30  # 15 × 2


def test_llm_brain_custom_system_prompt_injected():
    # p5.1b：AgentSpec 角色指令注入；JSON 协议仍由 brain 统一保证
    chat = FakeChat(['{"thought":"t","final":"ok"}'])
    brain = LlmBrain(
        model_id="deepseek-chat", tools=_registry(), chat_fn=chat,
        system_prompt="你是知识库问答 Agent。绝不编造制度条文。",
    )
    brain.next_step("任务", [])
    system = chat.calls[0][0]["content"]
    assert "知识库问答 Agent" in system
    assert "只能二选一输出" in system  # p6.3：A.工具 JSON / B.自然语言终答（可流式）
    assert "db_query" in system


def test_make_brain_falls_back_to_stub_without_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_brain_model", "deepseek-chat")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(settings, "siliconflow_api_key", "")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    brain = make_brain(_registry(), fallback_answer="[x] 处理完成")
    assert isinstance(brain, StubBrain)
    assert brain.next_step("t", []).final == "[x] 处理完成"  # 基线行为不变


def test_make_brain_uses_llm_when_key_present(monkeypatch):
    monkeypatch.setattr(settings, "llm_brain_model", "deepseek-chat")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    brain = make_brain(_registry())
    assert isinstance(brain, LlmBrain)


# ---------- p6.3 流式模式 ----------
def _stream_brain(chat: FakeChat, on_content=None, on_thought=None) -> LlmBrain:
    return LlmBrain(
        model_id="deepseek-chat", tools=_registry(), chat_fn=chat, chat_stream_fn=chat.stream,
        stream=True, on_content=on_content, on_thought=on_thought,
    )


def test_stream_natural_language_is_chunked():
    chat = FakeChat(stream_chunks=["公司", "年假", "5天"])
    got: list[str] = []
    brain = _stream_brain(chat, on_content=got.append)
    step = brain.next_step("任务", [])
    assert step.final == "公司年假5天"
    assert step.streamed is True          # run_react 不重复整段发
    assert got == ["公司", "年假", "5天"]  # 逐字推过（真打字机）


def test_stream_json_action_not_chunked():
    chat = FakeChat(stream_chunks=['{"thought":"查库",', '"action":"db_query","action_input":{}}'])
    got: list[str] = []
    brain = _stream_brain(chat, on_content=got.append)
    step = brain.next_step("任务", [])
    assert step.action == "db_query"
    assert got == []                       # JSON 协议不逐字推（等完整解析）


def test_stream_thought_streamed_not_duplicated():
    chat = FakeChat(
        stream_chunks=['{"thought":"","action":"db_query","action_input":{}}'],
        reasoning_chunks=["先想一下"],
    )
    thoughts: list[str] = []
    brain = _stream_brain(chat, on_thought=thoughts.append)
    step = brain.next_step("任务", [])
    assert thoughts == ["先想一下"]
    assert step.thought == ""             # 已流式发过，Step 里置空防 run_react 重发


def test_stream_llm_error_stops_honestly():
    chat = FakeChat(fail_stream=True)
    brain = _stream_brain(chat)
    step = brain.next_step("任务", [])
    assert step.final is not None and "模型暂不可用" in step.final


def test_stream_usage_accumulates():
    chat = FakeChat(stream_chunks=["答", "案"])
    brain = _stream_brain(chat)
    brain.next_step("任务", [])
    assert brain.usage["total_tokens"] == 15
