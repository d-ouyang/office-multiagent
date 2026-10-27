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
    reg.register("db_query", lambda sql: {}, description="查询业务库",
                 parameters={"properties": {"sql": {"type": "string"}}})
    reg.register("rag_retrieve", lambda query: {}, description="检索知识库",
                 parameters={"properties": {"query": {"type": "string"}}})
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
    # 真解析失败 = 以 { 开头但不是合法 JSON（协议 A 的残缺输出）——如实停止，不猜不编
    chat = FakeChat(['{"thought":"查库","action":'])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.final is not None and "无法解析" in step.final
    assert step.action is None  # 不猜动作、不编数据


def test_llm_brain_natural_language_is_final_non_streaming():
    # p4.3b：非流式路径与流式一致——非 JSON 输出 = 协议 B 的自然语言终答
    # （此前非流式把它当"无法解析"停掉，multi 并行子任务因此全部哑火，真跑冒烟抓到）
    chat = FakeChat(["公司年假制度：入职满一年 5 天。"])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.final == "公司年假制度：入职满一年 5 天。"
    assert step.action is None
    assert step.streamed is False  # 非流式：由 run_react 整段发一次


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


# ---------- v2.0.0-p1.3：原生 tool_calls 双协议 ----------

from app.core.llm import ToolCall


class ToolCallsChat:
    """tool_calls 协议假 LLM：按脚本返回带/不带 tool_calls 的结果，并记录请求。"""

    def __init__(self, script: list[LlmResult]):
        self.script = list(script)
        self.calls: list[dict] = []

    def __call__(self, model_id: str, messages: list[dict], **kw) -> LlmResult:
        self.calls.append({"messages": messages, "kw": kw})
        return self.script.pop(0)

    def stream(self, model_id: str, messages: list[dict], **kw) -> LlmResult:  # pragma: no cover
        return self(model_id, messages, **kw)


def _call_result(calls: list[ToolCall], content: str = "") -> LlmResult:
    return LlmResult(content=content, prompt_tokens=10, completion_tokens=5, total_tokens=15, model="m", tool_calls=calls)


def test_tool_calls_brain_returns_structured_calls():
    chat = ToolCallsChat([
        _call_result([ToolCall(id="call_1", name="db_query", arguments={"sql": "SELECT 1"})], content="先查库"),
    ])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat, protocol="tool_calls")
    step = brain.next_step("任务", [])
    assert step.calls[0]["name"] == "db_query"
    assert step.calls[0]["arguments"] == {"sql": "SELECT 1"}
    assert step.calls[0]["id"] == "call_1"
    assert step.thought == "先查库"
    # 请求带 tools（OpenAI 格式），且 system 不再要求输出 JSON（Prompt 债务红线）
    assert chat.calls[0]["kw"]["tools"][0]["function"]["name"] == "db_query"
    assert "只能二选一输出" not in chat.calls[0]["messages"][0]["content"]


def test_tool_calls_brain_history_uses_tool_role_not_user_text():
    chat = ToolCallsChat([
        _call_result([], content="完成"),
    ])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat, protocol="tool_calls")
    history = [
        Step(thought="查库", action="db_query", action_input={"sql": "SELECT 1"},
             observation="rows=1", call_id="call_9"),
    ]
    brain.next_step("任务", history)
    msgs = chat.calls[0]["messages"]
    roles = [m["role"] for m in msgs]
    assert "tool" in roles
    assistant = next(m for m in msgs if m["role"] == "assistant")
    tool = next(m for m in msgs if m["role"] == "tool")
    assert assistant["tool_calls"][0]["id"] == "call_9"
    assert tool["tool_call_id"] == "call_9"
    assert tool["content"] == "rows=1"
    # 历史双写禁忌：观察只走 tool 角色，不拼进 user 文本
    user = next(m for m in msgs if m["role"] == "user")
    assert "rows=1" not in user["content"]


def test_tool_calls_brain_synthesizes_ids_for_json_history():
    chat = ToolCallsChat([_call_result([], content="done")])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat, protocol="tool_calls")
    history = [Step(action="db_query", action_input={"sql": "x"}, observation="ok")]
    brain.next_step("任务", history)
    assistant = next(m for m in chat.calls[0]["messages"] if m["role"] == "assistant")
    tool = next(m for m in chat.calls[0]["messages"] if m["role"] == "tool")
    assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"] == "call_1"


def test_tool_calls_brain_final_when_no_calls():
    chat = ToolCallsChat([LlmResult(content="答案是 5 天", model="m")])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat, protocol="tool_calls")
    step = brain.next_step("任务", [])
    assert step.final == "答案是 5 天"
    assert step.calls == []


def test_tool_calls_brain_bad_arguments_kept_with_parse_error():
    chat = ToolCallsChat([
        _call_result([ToolCall(id="c1", name="db_query", arguments={}, parse_error="arguments JSON 解析失败：EOF")]),
    ])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat, protocol="tool_calls")
    step = brain.next_step("任务", [])
    assert step.calls[0]["parse_error"] and "解析失败" in step.calls[0]["parse_error"]


def test_resolve_react_protocol_matrix(monkeypatch):
    from app.orchestration.brain import resolve_react_protocol

    reg_full = _registry()
    monkeypatch.setattr(settings, "react_protocol", "json")
    assert resolve_react_protocol(None, "deepseek-chat", reg_full) == "json"

    # auto：已点测支持且 Schema 齐全 → tool_calls
    monkeypatch.setattr(settings, "react_protocol", "auto")
    assert resolve_react_protocol(None, "deepseek-chat", reg_full) == "tool_calls"
    # auto：缺 Schema 工具 → json
    reg_raw = ToolRegistry()
    reg_raw.register("raw", lambda **kw: kw)
    assert resolve_react_protocol(None, "deepseek-chat", reg_raw) == "json"
    # auto：不支持 tools 的模型 → json
    assert resolve_react_protocol(None, "decision-llm", reg_full) == "json"
    # 显式 tool_calls + 不支持模型 → 回落 json（禁止硬开），且 warning 不抛
    monkeypatch.setattr(settings, "react_protocol", "tool_calls")
    assert resolve_react_protocol(None, "decision-llm", reg_full) == "json"
    # 显式 tool_calls + 支持模型 → tool_calls
    assert resolve_react_protocol(None, "deepseek-chat", reg_full) == "tool_calls"
    # 显式 tool_calls 但 Schema 不完整 → 回落 json（describe_openai 会排除缺 Schema 工具，硬开=静默退化）
    assert resolve_react_protocol(None, "deepseek-chat", reg_raw) == "json"
    # 非法配置回落 json
    assert resolve_react_protocol("bogus", "deepseek-chat", reg_full) == "json"
