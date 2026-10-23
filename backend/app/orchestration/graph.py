"""LangGraph 编排（p3.1/p3.2/p4.1/p4.2）：quota → planner → 条件路由 → 单 Agent ReAct / Orchestrator DAG → done。

- p4.1：单 Agent 走 `run_react`（§四.4），多 Agent 走 `run_dag`（§四.3）。Brain 用 StubBrain（LLM 后插）。
- p4.2：可选 quota 门（token 池 reserve，§十四）——余额不足 `interrupt()` 暂停（checkpointer 存档），
  充值后 `Command(resume=...)` 续跑；完成 settle 结算。seq 经【共享 RunEventEmitter】保持单调。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from ..core.config import settings
from ..core.decomposer import DAG, Subtask, decompose
from ..core.events import Event, RunEventEmitter, new_run_id
from ..core.model_registry import map_reasoning_effort
from ..core.planner import Plan, plan as run_plan
from ..core.router import decide
from ..core.token_pool import TokenPool
from ..core.db import get_engine
from .agents import build_default_registry, build_registry_for_spec, get_agent_spec
from .brain import make_brain
from .orchestrator import compose_subtask_text, run_dag
from .react import run_react

logger = logging.getLogger(__name__)


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
    model: str | None            # p6.5：本次任务的对话模型（优先级：请求>会话>默认）
    effort: str | None           # low/medium/high/max，仅推理模型会传给 API
    context_parts: dict[str, str]


def _emit_context(state: TaskState, system: str, tools, emitter: RunEventEmitter, emit: Callable[[Event], None]) -> None:
    from ..core.model_registry import load_registry
    from .brain import _PROTOCOL_TMPL
    from .memory import context_items

    parts = dict(state.get("context_parts") or {})
    if "current" not in parts:
        parts["current"] = state.get("text") or ""
    tool_text = "\n".join(item.get("description") or "" for item in tools.describe())
    mid = state.get("model") or settings.llm_brain_model
    window = 128000
    registry = load_registry()
    entry = next((m for m in registry.get("models", []) if m.id == mid), None)
    if entry is not None and int(getattr(entry, "context_window", 0) or 0) > 0:
        window = int(entry.context_window)
    items = context_items(parts, system=system, rules=_PROTOCOL_TMPL, tools=tool_text)
    used = sum(int(item["tokens"]) for item in items)
    emit(emitter.context_usage(window, used, items))


def _effort_for(state: TaskState) -> str | None:
    """按模型真实档位折叠界面三档。不支持的模型返回 None，请求里不带该字段。"""
    mid = state.get("model") or settings.llm_brain_model
    return map_reasoning_effort(mid, state.get("effort"))


def build_graph(
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
    *,
    token_pool: TokenPool | None = None,
    checkpointer: Any | None = None,
    username: str | None = None,
    user_id: int | None = None,
    task_id: str | None = None,
) -> Any:
    """构建编排图。token_pool 提供时前置 quota 门（reserve + 中断续跑）。

    username 有值时，read_document 只在该用户的上传目录里找文件。
    """
    tools = build_default_registry(
        get_engine(), username=username, user_id=user_id, task_id=task_id
    )

    def spec_agent_runner(base, state):
        """multi 的子任务执行器：按子任务 agent_type 取 AgentSpec（角色提示词+工具白名单）。

        p4.3a：接上游结果——任务文本 = intent + 直接上游的 final 摘要（compose_subtask_text），
        下游不再"只看 intent 盲跑"。

        p4.3b：并行安全——multi 子任务脑走【非流式】（stream=False）。层内并行时若各子任务
        逐字推 content_delta，多 Agent 的终答会字符级交错成乱码；块状推送下每个子任务的
        思考/终答是完整事件，并行只加速执行、不破坏可读性。单 Agent 路径（single_node）
        仍是逐字流（打字机），不受影响。
        """

        def _run(st, upstream=None):
            spec = get_agent_spec(st.agent_type)
            spec_tools = build_registry_for_spec(spec, base)
            brain = make_brain(
                spec_tools,
                fallback_answer=f"[{st.agent_type}] 完成 {st.intent}",
                system_prompt=spec.system_prompt,
                model_id=state.get("model"),
                stream=False,
                on_content=lambda c: emit(emitter.content_delta(c)),
                on_thought=lambda t: emit(emitter.thinking_delta(t)),
                reasoning_effort=_effort_for(state),
            )
            # 必须用主 emitter：子 emitter 的 seq 独立从 1 开始，会让主事件流 seq 乱序
            return run_react(
                compose_subtask_text(st.intent, upstream or {}),
                brain,
                spec_tools,
                emitter=emitter,
                emit=emit,
            )

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
        _emit_context(state, spec.system_prompt, spec_tools, emitter, emit)
        brain = make_brain(
            spec_tools, fallback_answer=f"[{agent}] 处理完成", system_prompt=spec.system_prompt,
            model_id=state.get("model"),
            stream=True,
            on_content=lambda c: emit(emitter.content_delta(c)),
            on_thought=lambda t: emit(emitter.thinking_delta(t)),
            reasoning_effort=_effort_for(state),
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
        results = run_dag(dag, emitter=emitter, emit=emit, agent_runner=spec_agent_runner(tools, state))
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
    sink: Callable[[Event], None] | None = None,
    model: str | None = None,
    effort: str | None = None,
    username: str | None = None,
    context_parts: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[Event]]:
    """跑一次编排。带 token_pool+user_id 时前置 reserve；余额不足→quota_paused 中断。

    p6.3：`sink` 每产生一个事件同步回调一次（供 /tasks 实时转发队列）；
    不传则仅收集到返回的 events 列表（旧行为，测试依赖）。
    p6.5：`model` 指定本次对话模型（None→settings.llm_brain_model）。
    """
    run_id = new_run_id()
    turn_id = new_run_id()
    emitter = RunEventEmitter(run_id, turn_id)
    model_id = model or settings.llm_brain_model
    events: list[Event] = []

    def emit(ev: Event) -> None:
        events.append(ev)
        if sink is not None:
            sink(ev)

    checkpointer = MemorySaver() if token_pool is not None else None
    graph = build_graph(
        emitter,
        emit,
        token_pool=token_pool,
        checkpointer=checkpointer,
        username=username,
        user_id=user_id,
        task_id=run_id,
    )
    cfg = {"configurable": {"thread_id": run_id}}
    init: dict[str, Any] = {
        "text": text,
        "run_id": run_id,
        "turn_id": turn_id,
        "model": model,
        "effort": effort,
        "context_parts": context_parts or {"current": text},
    }
    if user_id is not None:
        init["user_id"] = user_id
        init["estimate"] = estimate

    try:
        state = graph.invoke(init, cfg)
    except Exception as e:  # noqa: BLE001 - 编排崩溃也要给流一个体面的 done（前端能收尾）
        logger.exception("编排执行失败 run_id=%s", run_id)
        emit(emitter.error(f"编排执行失败：{e}"))
        emit(emitter.done("failed", model=model_id))
        return (
            {
                "run_id": run_id,
                "thread_id": run_id,
                "status": "failed",
                "route": None,
                "result": "",
            },
            events,
        )

    if "__interrupt__" in state:
        payload = state["__interrupt__"][0].value if state["__interrupt__"] else {}
        emit(
            emitter.quota_paused(
                "余额不足，已暂停",
                balance=int(payload.get("balance") or 0),
                needed=int(payload.get("needed") or 0),
            )
        )
        emit(emitter.done("paused_insufficient_quota", model=model_id))
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
        token_pool.settle(
            user_id, estimate, actual, task_id=run_id,
            model=state.get("model") or settings.llm_brain_model,  # p6.4/p6.5：落账记实际模型
        )
    emit(
        emitter.done(
            state.get("route", "single"),
            tokens_used=int(state.get("tokens_used", 0)),
            model=state.get("model") or model_id,
        )
    )
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
