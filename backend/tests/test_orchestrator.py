"""Orchestrator 调度测试（p4.1，§四.3：按 DAG 拓扑分层执行 + 汇总；p4.3a：上游结果传递）。"""
import pytest

from app.core.decomposer import DAG, Subtask
from app.core.events import EventType, RunEventEmitter
from app.orchestration.react import AgentResult, StubBrain, run_react
from app.orchestration.tools import ToolRegistry
from app.orchestration.orchestrator import compose_subtask_text, run_dag, topo_levels


def _dag(pairs):
    return DAG(subtasks=[Subtask(id=i, agent_type=f"{i}_agent", intent=i, depends_on=d) for i, d in pairs])


def test_topo_levels_layering():
    dag = _dag([("cleaning", []), ("analysis", ["cleaning"]), ("report", ["analysis"]), ("rag", [])])
    levels = topo_levels(dag)
    assert {s.id for s in levels[0]} == {"cleaning", "rag"}  # 同层可并行
    assert [s.id for s in levels[1]] == ["analysis"]
    assert [s.id for s in levels[2]] == ["report"]


def test_topo_levels_cycle_raises():
    with pytest.raises(ValueError, match="环"):
        topo_levels(_dag([("a", ["b"]), ("b", ["a"])]))


def test_run_dag_executes_in_topo_order_and_aggregates():
    dag = _dag([("cleaning", []), ("analysis", ["cleaning"])])
    em = RunEventEmitter("r", "t")
    events: list = []
    order: list[str] = []

    def runner(st, upstream=None):
        order.append(st.id)
        return run_react(
            st.intent, StubBrain(f"{st.id}-done"), ToolRegistry(), emitter=RunEventEmitter("s", st.id)
        )

    results = run_dag(dag, emitter=em, emit=events.append, agent_runner=runner)
    assert order == ["cleaning", "analysis"]  # 拓扑序
    assert set(results) == {"cleaning", "analysis"}
    assert results["analysis"].final == "analysis-done"
    statuses = [e for e in events if e.type == EventType.STATUS]
    assert len(statuses) >= 4  # 每个子任务 running + done


# --------------------------------------------------------------------------- #
# p4.3a：上游结果传递给下游
# --------------------------------------------------------------------------- #

def test_run_dag_passes_upstream_results_to_runner():
    dag = _dag([("cleaning", []), ("analysis", ["cleaning"])])
    em = RunEventEmitter("r", "t")
    seen: dict[str, dict] = {}

    def runner(st, upstream=None):
        seen[st.id] = upstream or {}
        return run_react(st.intent, StubBrain(f"{st.id}-done"), ToolRegistry())

    run_dag(dag, emitter=em, emit=lambda e: None, agent_runner=runner)
    assert seen["cleaning"] == {}  # 无依赖 → 空上游
    assert set(seen["analysis"]) == {"cleaning"}
    assert seen["analysis"]["cleaning"].final == "cleaning-done"


def test_run_dag_upstream_only_contains_direct_dependencies():
    # 传递的是【直接】上游：report 只该拿到 analysis，不该拿到 transitive 的 cleaning
    dag = _dag([("cleaning", []), ("analysis", ["cleaning"]), ("report", ["analysis"])])
    em = RunEventEmitter("r", "t")
    seen: dict[str, set] = {}

    def runner(st, upstream=None):
        seen[st.id] = set(upstream or {})
        return run_react(st.intent, StubBrain(f"{st.id}-done"), ToolRegistry())

    run_dag(dag, emitter=em, emit=lambda e: None, agent_runner=runner)
    assert seen["report"] == {"analysis"}


def test_compose_subtask_text_without_upstream_is_intent_only():
    # 向后兼容：无上游时与 p4.1 行为完全一致
    assert compose_subtask_text("analysis", {}) == "analysis 任务"
    assert compose_subtask_text("analysis", None) == "analysis 任务"


def test_compose_subtask_text_includes_upstream_final():
    res = AgentResult(final="清洗掉 12 行重复", steps=[], iterations=1)
    text = compose_subtask_text("analysis", {"cleaning": res})
    assert "清洗掉 12 行重复" in text
    assert "上游子任务结果" in text
    assert "基于上述上游结果" in text


def test_compose_subtask_text_marks_upstream_failure_honestly():
    res = AgentResult(final="已达 max_iterations=10", steps=[], iterations=10, hit_cap=True)
    text = compose_subtask_text("analysis", {"cleaning": res})
    assert "未完成" in text
    assert "不要当作已完成的数据" in text  # 失败不可伪装成结果（§四.5）


def test_compose_subtask_text_truncates_long_upstream():
    res = AgentResult(final="数" * 5000, steps=[], iterations=1)
    text = compose_subtask_text("analysis", {"cleaning": res}, max_chars_per_upstream=100)
    assert "已截断" in text
    assert "数" * 5000 not in text  # 长上游不许原样进上下文（p6.7/p6.9 教训）


# --------------------------------------------------------------------------- #
# p4.3b：层内并行（ThreadPoolExecutor）+ 回落串行
# --------------------------------------------------------------------------- #

def test_run_dag_parallel_within_layer():
    # 同层 3 个无依赖子任务并行：总耗时 ≈ max(单任务 0.1s)，串行会 ≥0.3s
    import time

    dag = _dag([("a", []), ("b", []), ("c", [])])
    em = RunEventEmitter("r", "t")

    def runner(st, upstream=None):
        time.sleep(0.1)
        return run_react(st.intent, StubBrain(f"{st.id}-done"), ToolRegistry())

    t0 = time.monotonic()
    results = run_dag(dag, emitter=em, emit=lambda e: None, agent_runner=runner, max_concurrency=3)
    elapsed = time.monotonic() - t0
    assert set(results) == {"a", "b", "c"}
    assert elapsed < 0.25


def test_run_dag_serial_when_max_concurrency_one():
    # 回落开关：max_concurrency=1 → 串行基线，执行顺序确定（与 p4.1 一致）
    dag = _dag([("a", []), ("b", []), ("c", [])])
    em = RunEventEmitter("r", "t")
    order: list[str] = []

    def runner(st, upstream=None):
        order.append(st.id)
        return run_react(st.intent, StubBrain(f"{st.id}-done"), ToolRegistry())

    results = run_dag(dag, emitter=em, emit=lambda e: None, agent_runner=runner, max_concurrency=1)
    assert order == ["a", "b", "c"]
    assert list(results) == ["a", "b", "c"]  # 汇总顺序确定（可对账）


def test_run_dag_parallel_preserves_dependencies():
    # 并行不破坏层间依赖：下游仍只拿到直接上游的结果
    dag = _dag([("a", []), ("b", []), ("c", ["a", "b"])])
    em = RunEventEmitter("r", "t")
    seen: dict[str, dict] = {}

    def runner(st, upstream=None):
        seen[st.id] = dict(upstream or {})
        return run_react(st.intent, StubBrain(f"{st.id}-done"), ToolRegistry())

    run_dag(dag, emitter=em, emit=lambda e: None, agent_runner=runner, max_concurrency=3)
    assert seen["a"] == {} and seen["b"] == {}
    assert set(seen["c"]) == {"a", "b"}
    assert seen["c"]["a"].final == "a-done" and seen["c"]["b"].final == "b-done"


def test_run_dag_events_seq_unique_under_parallel():
    # 并发子任务经主 emitter 推事件：seq 必须无重复（EventSequence 加锁，events.py）
    dag = _dag([("a", []), ("b", []), ("c", []), ("d", [])])
    em = RunEventEmitter("r", "t")
    events: list = []

    def runner(st, upstream=None):
        for i in range(5):
            events.append(em.thinking_delta(f"{st.id}-{i}"))
        return run_react(st.intent, StubBrain(f"{st.id}-done"), ToolRegistry(), emitter=em, emit=events.append)

    run_dag(dag, emitter=em, emit=events.append, agent_runner=runner, max_concurrency=4)
    seqs = [e.seq for e in events]
    assert len(set(seqs)) == len(seqs)            # 并发下无重复 seq
    assert sorted(seqs) == list(range(1, len(seqs) + 1))  # 且连续无跳号
