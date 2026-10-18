"""Orchestrator 调度（p4.1）——设计文档 §四.3/§六：按 DAG 拓扑分层执行，层内互不依赖（可并行），
层间有依赖；各子任务跑单 Agent ReAct，最后汇总。基线层内串行（确定性、可测），
并行化（asyncio.gather）留作后续，接口已按"层"组织好。
"""
from __future__ import annotations

from collections.abc import Callable

from ..core.decomposer import DAG, Subtask
from ..core.events import Event, RunEventEmitter
from .react import AgentResult, StubBrain, run_react
from .tools import ToolRegistry


def topo_levels(dag: DAG) -> list[list[Subtask]]:
    """把 DAG 分成拓扑层：同层子任务依赖都已满足（可并行），按层推进。有环抛错。"""
    done: set[str] = set()
    remaining = {s.id: s for s in dag.subtasks}
    levels: list[list[Subtask]] = []
    while remaining:
        layer = [s for s in remaining.values() if all(d in done for d in s.depends_on)]
        if not layer:
            raise ValueError("DAG 存在环，无法分层调度")
        levels.append(layer)
        for s in layer:
            done.add(s.id)
            del remaining[s.id]
    return levels


def run_dag(
    dag: DAG,
    *,
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
    agent_runner: Callable[[Subtask], AgentResult],
) -> dict[str, AgentResult]:
    """按拓扑层执行各子任务（层内串行基线），返回 {subtask_id: AgentResult}。"""
    results: dict[str, AgentResult] = {}
    for level in topo_levels(dag):
        for st in level:
            emit(emitter.status(st.agent_type, "running", subtask_id=st.id))
            results[st.id] = agent_runner(st)
            emit(emitter.status(st.agent_type, "done", subtask_id=st.id))
    return results


def default_agent_runner(
    tools: ToolRegistry | None = None,
) -> Callable[[Subtask], AgentResult]:
    """默认子任务执行器：用 StubBrain 跑一步 ReAct（无 LLM，闭环跑通用）。"""
    reg = tools if tools is not None else ToolRegistry()

    def _run(st: Subtask) -> AgentResult:
        em = RunEventEmitter("sub", st.id)
        return run_react(
            f"{st.intent} 任务",
            StubBrain(f"[{st.agent_type}] 完成 {st.intent}"),
            reg,
            emitter=em,
        )

    return _run
