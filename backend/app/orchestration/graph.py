"""LangGraph 编排（p3.1/p3.2/p4.1/p4.2）：quota → planner → 条件路由 → 单 Agent ReAct / Orchestrator DAG → done。

- p4.1：单 Agent 走 `run_react`（§四.4），多 Agent 走 `run_dag`（§四.3）。Brain 用 StubBrain（LLM 后插）。
- p4.2：可选 quota 门（token 池 reserve，§十四）——余额不足 `interrupt()` 暂停（checkpointer 存档），
  充值后 `Command(resume=...)` 续跑；完成 settle 结算。seq 经【共享 RunEventEmitter】保持单调。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from ..core.decomposer import DAG, Subtask, decompose
from ..core.events import Event, RunEventEmitter, new_run_id
from ..core.planner import Plan, plan as run_plan
from ..core.router import decide
from ..core.token_pool import TokenPool
from ..core.db import get_engine
from .agents import build_default_registry, build_registry_for_spec, get_agent_spec
from .brain import make_brain
from .orchestrator import run_dag
from .react import run_react


class TaskState(TypedDict, total=False):
    text: str
    run_id: str
    turn_id: str
    user_id: int
    estimate: int
    intents: list[str]
    score: float
    route: str
    primary_agent: str
    dag: dict
    reserved: int
    status: str
    tokens_used: int
    result: str


def build_graph(
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
    *,
    token_pool: TokenPool | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """构建编排图。token_pool 提供时前置 quota 门（reserve + 中断续跑）。"""
    tools = build_default_registry(get_engine())  # p5.1a：真实工具（db_query / rag_retrieve）

    def spec_agent_runner(base):
        """multi 的子任务执行器：按子任务 agent_type 取 AgentSpec（角色提示词+工具白名单）。"""

        def _run(st):
            spec = get_agent_spec(st.agent_type)
            spec_tools = build_registry_for_spec(spec, base)
            brain = make_brain(
                spec_tools,
                fallback_answer=f"[{st.agent_type}] 完成 {st.intent}",
                system_prompt=spec.system_prompt,
            )
            em = RunEventEmitter("sub", st.id)
            return run_react(f"{st.intent} 任务", brain, spec_tools, emitter=em)

        return _run

    def quota_node(state: TaskState) -> dict[str, Any]:
        user_id = state.get("user_id")
        estimate = int(state.get("estimate", 0))
        assert token_pool is not None
        res = token_pool.reserve(user_id, estimate, task_id=state.get("run_id"))
        if not res.ok:
            # 余额不足 → 中断暂停（§十四.3），等充值后续跑
            cur = token_pool.balance(user_id)
            interrupt({"type": "quota_paused", "balance": cur, "needed": estimate})
            # resume 后重试 reserve
            res = token_pool.reserve(user_id, estimate, task_id=state.get("run_id"))
            if not res.ok:
                return {"status": "paused_insufficient_quota"}
        return {"reserved": estimate, "status": "running"}

    def quota_router(state: TaskState) -> str:
        return "end" if state.get("status") == "paused_insufficient_quota" else "planner"

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
        # p5.1b：按 AgentSpec 装配（角色提示词 + 工具白名单）；无 key 回落 StubBrain（基线不变）
        spec = get_agent_spec(agent)
        spec_tools = build_registry_for_spec(spec, tools)
        # p5.2：向流上暴露"当前是谁在回答"（前端 Agent 徽章的数据源）
        emit(emitter.status(agent, "running"))
        brain = make_brain(
            spec_tools, fallback_answer=f"[{agent}] 处理完成", system_prompt=spec.system_prompt,
        )
        res = run_react(state["text"], brain, spec_tools, emitter=emitter, emit=emit)
        usage = getattr(brain, "usage", None) or {}
        return {"result": res.final, "tokens_used": int(usage.get("total_tokens", 0))}

    def multi_node(state: TaskState) -> dict[str, Any]:
        emit(emitter.status("orchestrator", "running"))
        dag = DAG(
            subtasks=[
                Subtask(
                    id=s["id"],
                    agent_type=s["agent_type"],
                    intent=s["intent"],
                    depends_on=list(s.get("depends_on", [])),
                )
                for s in state.get("dag", {}).get("subtasks", [])
            ]
        )
        results = run_dag(dag, emitter=emitter, emit=emit, agent_runner=spec_agent_runner(tools))
        summary = "；".join(f"{k}:{v.final}" for k, v in results.items())
        emit(emitter.content_delta(f"多 Agent 汇总 → {summary}"))
        emit(emitter.status("orchestrator", "done"))
        return {"result": f"[multi] {summary}"}

    g = StateGraph(TaskState)
    g.add_node("planner", planner_node)
    g.add_node("single", single_node)
    g.add_node("multi", multi_node)
    g.add_conditional_edges("planner", route_edge, {"single": "single", "multi": "multi"})
    g.add_edge("single", END)
    g.add_edge("multi", END)

    if token_pool is not None:
        g.add_node("quota", quota_node)
        g.set_entry_point("quota")
        g.add_conditional_edges("quota", quota_router, {"planner": "planner", "end": END})
    else:
        g.set_entry_point("planner")

    return g.compile(checkpointer=checkpointer)


def run_task(
    text: str,
    *,
    user_id: int | None = None,
    estimate: int = 0,
    token_pool: TokenPool | None = None,
) -> tuple[dict[str, Any], list[Event]]:
    """跑一次编排。带 token_pool+user_id 时前置 reserve；余额不足→quota_paused 中断。"""
    run_id = new_run_id()
    turn_id = new_run_id()
    emitter = RunEventEmitter(run_id, turn_id)
    events: list[Event] = []
    emit = events.append

    checkpointer = MemorySaver() if token_pool is not None else None
    graph = build_graph(emitter, emit, token_pool=token_pool, checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": run_id}}
    init: dict[str, Any] = {"text": text, "run_id": run_id, "turn_id": turn_id}
    if user_id is not None:
        init["user_id"] = user_id
        init["estimate"] = estimate

    state = graph.invoke(init, cfg)

    if "__interrupt__" in state:
        payload = state["__interrupt__"][0].value if state["__interrupt__"] else {}
        emit(
            emitter.quota_paused(
                "余额不足，已暂停",
                balance=int(payload.get("balance") or 0),
                needed=int(payload.get("needed") or 0),
            )
        )
        emit(emitter.done("paused_insufficient_quota"))
        return (
            {
                "run_id": run_id,
                "thread_id": run_id,
                "status": "paused_insufficient_quota",
                "route": None,
                "result": "",
            },
            events,
        )

    # 正常完成 → settle（actual=真实 LLM 用量；StubBrain 基线为 0，全额退回预扣）
    if token_pool is not None and user_id is not None:
        actual = int(state.get("tokens_used", 0))
        token_pool.settle(user_id, estimate, actual, task_id=run_id)
    emit(emitter.done(state.get("route", "single")))
    return (
        {
            "run_id": run_id,
            "thread_id": run_id,
            "status": "done",
            "route": state.get("route"),
            "intents": state.get("intents", []),
            "score": state.get("score", 0.0),
            "primary_agent": state.get("primary_agent"),
            "dag": state.get("dag"),
            "tokens_used": int(state.get("tokens_used", 0)),
            "result": state.get("result", ""),
        },
        events,
    )


def resume_task(
    graph: Any,
    thread_id: str,
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
) -> dict[str, Any]:
    """充值后续跑：对同一 graph + thread_id 发 Command(resume=True)。"""
    state = graph.invoke(Command(resume=True), {"configurable": {"thread_id": thread_id}})
    emit(emitter.done(state.get("route", "single")))
    return state
