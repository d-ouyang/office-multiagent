"""单任务 token 上限与钱包无关；这里验证并发占位和 ReAct 体面停止。"""
import pytest

from app.core.events import EventType, RunEventEmitter
from app.core.llm import LlmResult
from app.core.token_budget import TaskTokenBudget, TokenLimitReached
from app.orchestration.brain import LlmBrain
from app.orchestration.react import Step, run_react
from app.orchestration.tools import ToolRegistry


def test_reservations_share_one_global_task_limit():
    budget = TaskTokenBudget(1000)
    messages = [{"role": "user", "content": "短问题"}]
    first = budget.reserve_call(messages, desired_output_tokens=500)
    assert first is not None
    second = budget.reserve_call(messages, desired_output_tokens=500)
    assert second is not None
    with pytest.raises(TokenLimitReached):
        budget.reserve_call(messages, desired_output_tokens=500)
    first.complete(120)
    second.cancel()
    assert budget.used == 120
    assert budget.reserved == 0


class _CappedBrain:
    def __init__(self) -> None:
        self.calls = 0

    def next_step(self, task, history):
        self.calls += 1
        raise TokenLimitReached("cap")


def test_react_stops_at_model_boundary_and_keeps_done_shape():
    emitter = RunEventEmitter("r", "t")
    events = []
    result = run_react(
        "任务",
        _CappedBrain(),
        ToolRegistry(),
        emitter=emitter,
        emit=events.append,
        token_budget=TaskTokenBudget(50000),
    )
    assert result.hit_cap is True
    assert "50000" in result.final
    assert any(
        event.type == EventType.OBSERVATION and event.data.get("tool_id") == "token_limit"
        for event in events
    )


def test_llm_brain_sends_provider_output_cap_and_records_actual_usage():
    seen = {}

    def fake_chat(model_id, messages, **kwargs):
        seen["max_tokens"] = kwargs.get("max_tokens")
        return LlmResult(content="完成", prompt_tokens=80, completion_tokens=20, total_tokens=100)

    budget = TaskTokenBudget(5000)
    brain = LlmBrain(
        model_id="fake",
        tools=ToolRegistry(),
        chat_fn=fake_chat,
        token_budget=budget,
    )
    step = brain.next_step("短任务", [])
    assert step.final == "完成"
    assert 0 < seen["max_tokens"] < 5000
    assert budget.used == 100
