"""单 Agent ReAct 循环测试（p4.1，§四.4：Thought→Action→Observation，max_iterations 防跑飞）。"""
from app.core.events import EventType, RunEventEmitter
from app.orchestration.react import Step, StubBrain, run_react
from app.orchestration.tools import ToolRegistry


def test_final_in_one_step():
    em = RunEventEmitter("r", "t")
    events: list = []
    res = run_react("任务", StubBrain("答"), ToolRegistry(), emitter=em, emit=events.append)
    assert res.final == "答" and res.iterations == 1 and not res.hit_cap
    assert any(e.type == EventType.CONTENT_DELTA for e in events)


def test_max_iterations_cap_forces_stage_conclusion():
    class Loopy:
        def next_step(self, task, history):
            return Step(thought="想", action="noop", action_input={})

    reg = ToolRegistry()
    reg.register("noop", lambda: "obs")
    em = RunEventEmitter("r", "t")
    events: list = []
    res = run_react("任务", Loopy(), reg, max_iterations=3, emitter=em, emit=events.append)
    assert res.hit_cap and res.iterations == 3
    assert "max_iterations" in res.final
    starts = [e for e in events if e.type == EventType.TOOL_CALL_START]
    assert len(starts) == 3  # 每轮都推了 tool_call_start


def test_observation_recorded():
    class OneTool:
        def next_step(self, task, history):
            if history:
                return Step(final="终")
            return Step(action="echo", action_input={"x": "1"})

    reg = ToolRegistry()
    reg.register("echo", lambda x: f"echo:{x}")
    res = run_react("t", OneTool(), reg, emitter=RunEventEmitter("r", "t"))
    assert res.steps[0].observation == "echo:1"
    assert res.final == "终"


def test_tool_error_becomes_observation_not_crash():
    class OneBad:
        def next_step(self, task, history):
            if history:
                return Step(final="终")
            return Step(action="boom", action_input={})

    reg = ToolRegistry()

    def bad():
        raise ValueError("x")

    reg.register("boom", bad)
    res = run_react("t", OneBad(), reg, emitter=RunEventEmitter("r", "t"))
    assert "x" in res.steps[0].observation  # 错误进 observation，不炸编排
