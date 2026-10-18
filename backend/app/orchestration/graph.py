"""LangGraph 编排骨架（p3.1）：planner → 条件路由 → 单/多 Agent 桩节点 → done。

证明「路由真正驱动 LangGraph 控制流」。真实单 Agent ReAct / Orchestrator 在 Phase 4；
本模块节点先推 NDJSON 状态事件（§15.1）并返回桩结果。seq 经【共享 RunEventEmitter】
保持单调（前端按 seq 排序，§15.1）——不在各节点各建 emitter，否则 seq 会重头。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from ..core.events import Event, RunEventEmitter, new_run_id
from ..core.planner import plan as run_plan
from ..core.router import decide


class TaskState(TypedDict, total=False):
    text: str
    run_id: str
    turn_id: str
    intents: list[str]
    score: float
    route: str
    primary_agent: str
    result: str


def build_graph(emitter: RunEventEmitter, emit: Callable[[Event], None]) -> Any:
    """构建编排图。emit 把节点内事件抛给调用方（收集或流式）。"""

    def planner_node(state: TaskState) -> dict[str, Any]:
        p = run_plan(state["text"])
        d = decide(p)
        emit(emitter.thinking_delta(f"识别意图 {p.intents or ['general']}，复杂度分 {p.score}"))
        emit(emitter.status("planner", "done"))
        return {
            "intents": p.intents,
            "score": p.score,
            "route": d.mode,
            "primary_agent": d.primary_agent,
        }

    def route_edge(state: TaskState) -> str:
        return state.get("route", "single")

    def single_node(state: TaskState) -> dict[str, Any]:
        agent = state.get("primary_agent", "general")
        emit(emitter.status(agent, "running"))
        result = f"[single:{agent}] 桩结果（单 Agent ReAct 见 Phase 4）"
        emit(emitter.status(agent, "done"))
        emit(emitter.content_delta(result))
        return {"result": result}

    def multi_node(state: TaskState) -> dict[str, Any]:
        emit(emitter.status("orchestrator", "running"))
        result = f"[multi:{','.join(state.get('intents', []))}] 桩结果（Orchestrator 多 Agent 见 Phase 4）"
        emit(emitter.status("orchestrator", "done"))
        emit(emitter.content_delta(result))
        return {"result": result}

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
        "result": final.get("result", ""),
    }
    return result, events
