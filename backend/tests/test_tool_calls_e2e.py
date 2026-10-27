"""v2.0.0-p1.6：json 与 tool_calls 两协议 E2E 对照——同一任务输出同形 NDJSON 事件。

前端零改动的验收底线：除 thinking_delta（思考文案本就由模型自由生成）外，
tool_call_start/end、observation、content_delta 的事件类型与关键字段完全一致。
"""
from app.core.events import EventType, RunEventEmitter
from app.core.llm import LlmResult, ToolCall
from app.orchestration.brain import LlmBrain
from app.orchestration.react import run_react
from app.orchestration.tools import ToolRegistry


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("echo", lambda x: f"echo:{x}", description="回声",
                 parameters={"properties": {"x": {"type": "string"}}})
    return reg


class _JsonScriptBrain(LlmBrain):
    """json 协议：按脚本吐 ReAct JSON / 自然语言终答。"""

    def __init__(self, script: list[str]):
        super().__init__(model_id="deepseek-chat", tools=_registry(), protocol="json")

        class _Chat:
            def __call__(_self, model_id, messages, **kw):
                return LlmResult(content=script.pop(0), model=model_id)

        self._chat = _Chat()


class _ToolCallsScriptBrain(LlmBrain):
    """tool_calls 协议：按脚本吐结构化调用 / 自然语言终答。"""

    def __init__(self, script: list[LlmResult]):
        super().__init__(model_id="deepseek-chat", tools=_registry(), protocol="tool_calls")

        class _Chat:
            def __call__(_self, model_id, messages, **kw):
                return script.pop(0)

        self._chat = _Chat()


def _event_shape(events: list) -> list[tuple]:
    return [
        (e.type.value, e.data.get("name"), e.data.get("input"), e.data.get("delta"), e.data.get("success"))
        for e in events
        if e.type.value in ("tool_call_start", "tool_call_end", "observation", "content_delta")
    ]


def test_json_and_tool_calls_produce_same_event_shape():
    scenario_json = [
        '{"thought":"调用回声","action":"echo","action_input":{"x":"你好"}}',
        "工具结果已拿到：echo:你好。",
    ]
    scenario_calls = [
        LlmResult(content="调用回声", model="m", tool_calls=[
            ToolCall(id="call_1", name="echo", arguments={"x": "你好"}),
        ]),
        LlmResult(content="工具结果已拿到：echo:你好。", model="m"),
    ]

    events_json: list = []
    res_json = run_react("任务", _JsonScriptBrain(scenario_json), _registry(),
                         emitter=RunEventEmitter("r", "t"), emit=events_json.append)
    events_calls: list = []
    res_calls = run_react("任务", _ToolCallsScriptBrain(scenario_calls), _registry(),
                          emitter=RunEventEmitter("r", "t"), emit=events_calls.append)

    assert res_json.final == res_calls.final == "工具结果已拿到：echo:你好。"
    shape_json = _event_shape(events_json)
    shape_calls = _event_shape(events_calls)
    assert shape_json == shape_calls
    # 关键事件逐类校验（防 _event_shape 悄悄丢类）
    kinds_json = [e.type.value for e in events_json]
    kinds_calls = [e.type.value for e in events_calls]
    for kind in ("tool_call_start", "observation", "tool_call_end", "content_delta"):
        assert kind in kinds_json and kind in kinds_calls


def test_multi_call_scenario_matches_golden_expectation():
    """golden「一轮多工具」：两个 call 全部执行并回填后给终答。"""
    brain = _ToolCallsScriptBrain([
        LlmResult(content="", model="m", tool_calls=[
            ToolCall(id="c1", name="echo", arguments={"x": "1"}),
            ToolCall(id="c2", name="echo", arguments={"x": "2"}),
        ]),
        LlmResult(content="两个结果都拿到了。", model="m"),
    ])
    events: list = []
    res = run_react("任务", brain, _registry(), emitter=RunEventEmitter("r", "t"), emit=events.append)
    assert res.final == "两个结果都拿到了。"
    starts = [e.data["tool_id"] for e in events if e.type == EventType.TOOL_CALL_START]
    ends = [e.data["tool_id"] for e in events if e.type == EventType.TOOL_CALL_END]
    assert starts == ends == ["c1", "c2"]  # id 一一对应，全部回填
