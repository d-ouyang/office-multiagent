"""LangGraph 编排（p3.1/p3.2/p4.1）：planner → 条件路由 → 单 Agent ReAct / Orchestrator DAG → done。

p4.1 起节点跑【真实编排机器】：单 Agent 走 `run_react`（§四.4 ReAct 循环 + max_iterations 防跑飞），
多 Agent 走 `run_dag`（§四.3 按 DAG 拓扑分层调度 + 汇总）。Brain 用确定性 StubBrain（无 LLM、
可测），LLM brain 后续按 Brain 协议插入。seq 经【共享 RunEventEmitter】保持单调（§15.1）。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from ..core.decomposer import DAG, Subtask, decompose
from ..core.events import Event, RunEventEmitter, new_run_id
from ..core.planner import Plan, plan as run_plan
from ..core.router import decide
from .orchestrator import default_agent_runner, run_dag
from .react import StubBrain, run_react
from .tools import ToolRegistry


class TaskState(TypedDict, total=False):
    text: str
    run_id: str
    turn_id: str
    intents: list[str]
    score: float
    route: str
    primary_agent: str
    dag: dict
    result: str


def build_graph(emitter: RunEventEmitter, emit: Callable[[Event], None]) -> Any:
    """构建编排图。emit 把节点内事件抛给调用方（收集或流式）。"""
    tools = ToolRegistry()  # 基线无注册工具；Phase 5 办公能力池往里 register

    def planner_node(state: TaskState) -> dict[str, Any]:
        p: Plan = run_plan(state["text"])
        d = decide(p)
        emit(emitter.thinking_delta(f"识别意图 {p.intents or ['general']}，复杂度分 {p.score}"))
        out: dict[str, Any] = {
            "intents": p.intents,
            "score": p.score,
            "route": d.mode,
            "primary_agent": d.primary_agent,
        }
        if d.mode == "multi":
            dag = decompose(p)
            out["dag"] = dag.to_dict()
            emit(
                emitter.thinking_delta(
                    f"拆成 {len(dag.subtasks)} 个子任务，拓扑序 {[s.id for s in dag.topo_order()]}"
                )
            )
        emit(emitter.status("planner", "done"))
        return out

    def route_edge(state: TaskState) -> str:
        return state.get("route", "single")

    def single_node(state: TaskState) -> dict[str, Any]:
        agent = state.get("primary_agent", "general")
        res = run_react(
            state["text"],
            StubBrain(f"[{agent}] 处理完成"),
            tools,
            emitter=emitter,
            emit=emit,
        )
        return {"result": res.final}

    def multi_node(state: TaskState) -> dict[str, Any]:
        emit(emitter.status("orchestrator", "running"))
        dag_dict = state.get("dag", {})
        # 由 dict 重建 DAG 对象（state 里存的是 to_dict 结果）
        dag = DAG(
            subtasks=[
                Subtask(
                    id=s["id"],
                    agent_type=s["agent_type"],
                    intent=s["intent"],
                    depends_on=list(s.get("depends_on", [])),
                )
                for s in dag_dict.get("subtasks", [])
            ]
        )
        results = run_dag(
            dag,
            emitter=emitter,
            emit=emit,
            agent_runner=default_agent_runner(tools),
        )
        summary = "；".join(f"{k}:{v.final}" for k, v in results.items())
        emit(emitter.content_delta(f"多 Agent 汇总 → {summary}"))
        emit(emitter.status("orchestrator", "done"))
        return {"result": f"[multi] {summary}"}

    g = StateGraph(TaskState)
    g.add_node("planner", planner_node)
    g.add_node("single", single_node)
    g.add_node("multi", multi_node)
    g.set_entry_point("planner")
    g.add_conditional_edges("planner", route_edge, {"single": "single", "multi": "multi"})
    g.add_edge("single", END)
    g.add_edge("multi", END)
    return g.compile()


def run_task(text: str) -> tuple[dict[str, Any], list[Event]]:
    """跑一次编排，返回 (结果摘要, 事件序列)。确定性、可测。"""
    run_id = new_run_id()
    turn_id = new_run_id()
    emitter = RunEventEmitter(run_id, turn_id)
    events: list[Event] = []
    emit = events.append

    graph = build_graph(emitter, emit)
    final = graph.invoke({"text": text, "run_id": run_id, "turn_id": turn_id})
    emit(emitter.done(final.get("route", "single")))

    result = {
        "run_id": run_id,
        "turn_id": turn_id,
        "route": final.get("route"),
        "intents": final.get("intents", []),
        "score": final.get("score", 0.0),
        "primary_agent": final.get("primary_agent"),
        "dag": final.get("dag"),
        "result": final.get("result", ""),
    }
    return result, events
