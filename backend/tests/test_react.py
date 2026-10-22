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
            return Step(thought="想", action="noop", action_input={"n": len(history)})

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


# ---------- p6.7 过程透明/失败兜底 ----------
def test_observation_summary_truncates_dict_content():
    from app.orchestration.react import _summarize_observation

    # p6.9：read_document max_chars=50000、摘要 content 截 24000——
    # 2 万字文档全量进上下文（通读）；超 24000 才截断并标注
    big = {"file_name": "dev/a.md", "total_chars": 60000, "content": "x" * 60000}
    s = _summarize_observation(big)
    assert "file_name=dev/a.md" in s
    assert "已截断展示" in s
    assert len(s) < 50000  # 24000 上限 + 字段摘要

    full = {"file_name": "dev/b.md", "total_chars": 20965, "content": "y" * 20965}
    s2 = _summarize_observation(full)
    assert "已截断展示" not in s2  # 2 万字文档不再截断（通读）
    assert s2.count("y") == 20965


def test_observation_summary_keeps_sales_report():
    from app.orchestration.react import _summarize_observation

    text = _summarize_observation(
        {"complete": True, "report": "销售报表\n状态：完成\n结果：\n- 订单数 29，指标值 6044.87", "missing": []}
    )
    assert "销售报表" in text
    assert "6044.87" in text
    assert "complete=true" in text or "complete=True" in text


def test_repeat_same_tool_does_not_call_again():
    calls = {"n": 0}

    def sales_report(**_kwargs):
        calls["n"] += 1
        return {"complete": True, "report": "销售报表 6044.87"}

    class RepeatBrain:
        def next_step(self, task, history):
            return Step(thought="再查一次", action="sales_report", action_input={"metric": "sum_pay"})

    reg = ToolRegistry()
    reg.register("sales_report", sales_report, description="报表")
    res = run_react("出报表并给建议", RepeatBrain(), reg, max_iterations=6)
    assert calls["n"] == 1
    assert "6044.87" in (res.steps[0].observation or "")
    assert res.hit_cap is True
    assert "6044.87" in res.final


def test_invalid_action_streak_forces_honest_finish():
    from app.orchestration.react import run_react
    from app.orchestration.brain import LlmBrain
    from app.orchestration.tools import ToolRegistry

    reg = ToolRegistry()
    reg.register("db_query", lambda sql: {}, description="查库")
    # LLM 连续给无效 action（幻觉 none）——工程兜底必须强制如实收尾，不空转
    class NoneBrain:
        def next_step(self, task, history):
            return Step(thought="想总结但幻觉工具", invalid_action=True)

    res = run_react("读文件总结", NoneBrain(), reg, max_iterations=10)
    assert res.hit_cap is True
    assert "无效工具名" in res.final
    assert res.iterations == 2  # 连续 2 次即收尾，不跑满 10 步


def test_chunked_final_emits_multiple_deltas():
    from app.core.events import RunEventEmitter
    from app.orchestration.react import run_react
    from app.orchestration.tools import ToolRegistry

    reg = ToolRegistry()
    em = RunEventEmitter("r", "t")
    events: list = []

    class ChunkBrain:
        def next_step(self, task, history):
            return Step(thought="", final="一二三四五六七八九十", streamed=True, chunked=True)

    run_react("任务", ChunkBrain(), reg, emitter=em, emit=events.append)
    deltas = [e for e in events if e.type.value == "content_delta"]
    assert len(deltas) == 2  # 10 字按 5 字/块 → 2 块（打字机）
    assert "".join(d.data["delta"] for d in deltas) == "一二三四五六七八九十"
