"""Orchestrator 调度测试（p4.1，§四.3：按 DAG 拓扑分层执行 + 汇总）。"""
import pytest

from app.core.decomposer import DAG, Subtask
from app.core.events import EventType, RunEventEmitter
from app.orchestration.react import StubBrain, run_react
from app.orchestration.tools import ToolRegistry
from app.orchestration.orchestrator import run_dag, topo_levels


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

    def runner(st):
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
