"""LangGraph 编排（p3.1/p3.2/p4.1/p4.2）：quota → planner → 条件路由 → 单 Agent ReAct / Orchestrator DAG → done。

- p4.1：单 Agent 走 `run_react`（§四.4），多 Agent 走 `run_dag`（§四.3）。Brain 用 StubBrain（LLM 后插）。
- p4.2：可选 quota 门（token 池 reserve，§十四）——余额不足 `interrupt()` 暂停（checkpointer 存档），
  充值后 `Command(resume=...)` 续跑；完成 settle 结算。seq 经【共享 RunEventEmitter】保持单调。
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from ..core.config import settings
from ..core.decomposer import DAG, Subtask, decompose
from ..core.events import Event, RunEventEmitter, new_run_id
from ..core.intent_decision import resolve_intent
from ..core.model_registry import map_reasoning_effort
from ..core.planner import Plan
from ..core.router import decide
from ..core.runs import RunCancelled, should_cancel
from ..core.token_pool import TokenPool
from ..core.token_budget import TaskTokenBudget, TokenLimitReached
from ..core.db import get_engine
from .agents import build_default_registry, build_registry_for_spec, get_agent_spec
from .brain import make_brain
from .orchestrator import compose_subtask_text, run_dag
from .react import run_react
from .tools import ToolRegistry
from .validator import check_and_report

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
    raw_text: str | None          # p6.30：本轮用户原文（planner 只看它，不被注入块污染）
    validation: dict[str, Any] | None  # p6.29：终答数字对账结果（None=未校验/跳过）
    route_text: str
    planning_tokens: int
    intent_source: str
    token_limit_reached: bool


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


def _validate_and_flag(
    result: Any,
    task: str,
    *,
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
    label: str,
) -> dict[str, Any] | None:
    """p6.29：终答数字对账（轻量结果校验器）。对不上时发 observation 事件 +
    WARNING 日志，不阻断不重跑；事件随 trace 落库，历史重建可见。"""
    report = check_and_report(
        final=result.final,
        observations=[s.observation or "" for s in result.steps],
        task=task,
        on_mismatch=lambda rep: emit(
            emitter.observation(
                "result_validator",
                f"⚠️ 结果校验（{label}）：终答中的数字 {('、'.join(rep.unmatched))} "
                "未在工具观察或任务原文中出现，可能为模型推断或笔误，请注意核对。",
            )
        ),
        label=label,
    )
    if report.skipped:
        return None
    return {"checked": report.checked, "unmatched": report.unmatched}


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
    should_cancel: Callable[[], bool] | None = None,
) -> Any:
    """构建编排图。token_pool 提供时前置 quota 门（reserve + 中断续跑）。

    username 有值时，read_document 只在该用户的上传目录里找文件。
    p7.1：should_cancel() 为真时在步骤边界抛 RunCancelled（用户主动暂停）。
    """
    tools = build_default_registry(
        get_engine(), username=username, user_id=user_id, task_id=task_id
    )
    from ..core.runtime_settings import task_token_limit

    token_budget = TaskTokenBudget(task_token_limit())

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
                token_budget=token_budget,
            )
            extra_tokens = {"n": 0}  # p4.3d：强制收尾那次 LLM 调用的用量，最后并入账

            def _synthesize(reason: str, history) -> str:
                """护栏强制停止时，用【空工具池】脑把已有观察收尾成人话（防再次跑飞）。"""
                bare = make_brain(
                    ToolRegistry(),
                    fallback_answer="",
                    system_prompt=spec.system_prompt,
                    model_id=state.get("model"),
                    stream=False,
                    reasoning_effort=_effort_for(state),
                    token_budget=token_budget,
                )
                step = bare.next_step(
                    f"【强制收尾】{reason}。不要再调用任何工具，直接基于以上已获得的观察，"
                    "写面向用户的最终回答（中文：已完成什么、得到哪些数据、还缺什么）。",
                    history,
                )
                usage = getattr(bare, "usage", None) or {}
                extra_tokens["n"] += int(usage.get("total_tokens", 0))
                return (step.final or "").strip()

            # 必须用主 emitter：子 emitter 的 seq 独立从 1 开始，会让主事件流 seq 乱序
            res = run_react(
                # p4.3d：带上用户完整请求（否则子任务只看到"analysis 任务"，不知道分析什么）
                compose_subtask_text(
                    st.intent, upstream or {}, request_text=state.get("text", "")
                ),
                brain,
                spec_tools,
                emitter=emitter,
                emit=emit,
                synthesize=_synthesize,
                should_cancel=should_cancel,
                token_budget=token_budget,
            )
            # p4.3c：带出本子任务真实用量（含强制收尾），供 multi_node 汇总进 tokens_used（§十四 对账）
            usage = getattr(brain, "usage", None) or {}
            res.tokens_used = (
                int(usage.get("total_tokens", 0))
                + extra_tokens["n"]
                + int(getattr(res, "external_tokens", 0) or 0)
            )
            return res

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
        if should_cancel is not None and should_cancel():
            raise RunCancelled("用户暂停")
        # 原文独立时直接规则识别；依赖上文时仅用近期对话改写成独立问题。
        # 长期记忆和历史摘要绝不进改写/分类，避免「制度」等词再次劫持路由。
        original = state.get("raw_text") or state["text"]
        recent = str((state.get("context_parts") or {}).get("recent") or "")
        resolution = resolve_intent(original, recent, token_budget=token_budget)
        p: Plan = resolution.plan
        d = decide(p)
        if resolution.rewritten:
            emit(emitter.thinking_delta(f"指代改写：{resolution.route_text}"))
        elif resolution.rewrite_failed:
            emit(emitter.thinking_delta("检测到指代，但改写未得到可靠结果；按本轮原文继续"))
        emit(emitter.thinking_delta(f"识别意图 {p.intents or ['general']}，复杂度分 {p.score}"))
        if resolution.source == "decision_model":
            emit(
                emitter.thinking_delta(
                    f"决策小模型复核：{resolution.recommended_mode}，"
                    f"{resolution.reason or '已完成封闭分类'}"
                )
            )
        out: dict[str, Any] = {
            "intents": p.intents,
            "score": p.score,
            "route": d.mode,
            "primary_agent": d.primary_agent,
            "route_text": resolution.route_text,
            "planning_tokens": resolution.tokens_used,
            "intent_source": resolution.source,
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
            token_budget=token_budget,
        )
        res = run_react(
            state["text"],
            brain,
            spec_tools,
            emitter=emitter,
            emit=emit,
            should_cancel=should_cancel,
            token_budget=token_budget,
        )
        usage = getattr(brain, "usage", None) or {}
        validation = _validate_and_flag(
            res, state["text"], emitter=emitter, emit=emit, label=f"single:{agent}"
        )
        billed = (
            int(state.get("planning_tokens", 0))
            + int(usage.get("total_tokens", 0))
            + int(getattr(res, "external_tokens", 0) or 0)
        )
        return {
            "result": res.final,
            "tokens_used": billed,
            "validation": validation,
            "token_limit_reached": token_budget.limit_reached,
        }

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
        results = run_dag(
            dag,
            emitter=emitter,
            emit=emit,
            agent_runner=spec_agent_runner(tools, state),
            max_concurrency=settings.dag_max_concurrency,  # p4.3c：层内并行度配置化
            should_cancel=should_cancel,                  # p7.1：用户暂停
        )
        summary = "；".join(f"{k}:{v.final}" for k, v in results.items())
        # p4.3c：汇总各子任务真实用量（此前 multi 不返回 tokens_used，settle 时
        # actual=0 全额退回，多 Agent 消耗不计账——§十四 对账恒等式破洞）
        total_tokens = int(state.get("planning_tokens", 0)) + sum(
            int(getattr(r, "tokens_used", 0) or 0) for r in results.values()
        )
        # p6.30：每个子任务终答各自对账（观察取各子任务自己的 steps）
        validations: dict[str, Any] = {}
        for key, r in results.items():
            rep = _validate_and_flag(
                r, state["text"], emitter=emitter, emit=emit, label=f"multi:{key}"
            )
            if rep is not None:
                validations[key] = rep
        # p6.30：汇总脑重写最终答复——不再原样拼接各子任务终答（真跑事故：5 张表
        # 在子任务终答里出现一遍、汇总又整段重复一遍）。汇总脑只输出：核心结论 +
        # 交付物清单（文件名/行数），完整表格以文件为准。失败回落旧拼接（不阻断）。
        deliverables = [
            f"- {a.get('display_name') or a.get('file_name')}（{a['file_name']}）"
            for r in results.values()
            for a in (getattr(r, "assets", None) or [])
        ]
        fallback = f"[multi] {summary}"
        final_text = fallback
        try:
            synth = make_brain(
                ToolRegistry(),
                fallback_answer="",
                system_prompt="你是多 Agent 协作的汇总官。把各子任务结果整合成面向用户的最终答复。",
                model_id=state.get("model"),
                stream=True,
                on_content=lambda c: emit(emitter.content_delta(c)),
                on_thought=lambda t: emit(emitter.thinking_delta(t)),
                reasoning_effort=_effort_for(state),
                token_budget=token_budget,
            )
            task_lines = "\n".join(f"【{k}】{(v.final or '')[:2000]}" for k, v in results.items())
            asset_block = ("\n\n生成的文件：\n" + "\n".join(deliverables)) if deliverables else ""
            step = synth.next_step(
                "用户请求：" + (state.get("raw_text") or state.get("text", ""))[:2000]
                + "\n\n各子任务结果：\n" + task_lines + asset_block
                + "\n\n请写最终答复：先给核心结论（3-5 条），再列交付文件清单（如有）。"
                "不要重复完整表格内容（表格已在交付文件里），不要编造文件名和数字。",
                [],
            )
            if (step.final or "").strip():
                final_text = step.final.strip()
            usage = getattr(synth, "usage", None) or {}
            total_tokens += int(usage.get("total_tokens", 0))
        except TokenLimitReached:
            token_budget.limit_reached = True
            emit(
                emitter.observation(
                    "token_limit",
                    f"本次任务已达到全局 token 上限 {token_budget.limit}，"
                    "不再调用汇总模型；各子任务已有结果与文件均保留。",
                )
            )
            emit(emitter.content_delta(fallback))
        except Exception:  # noqa: BLE001 - 汇总脑失败回落拼接，不阻断
            logger.exception("multi 汇总脑失败（回落拼接）")
        emit(emitter.status("orchestrator", "done"))
        return {
            "result": final_text,
            "tokens_used": total_tokens,
            "validation": validations or None,
            "token_limit_reached": token_budget.limit_reached,
        }

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
    run_id: str | None = None,
    cancel_event: threading.Event | None = None,
    raw_text: str | None = None,
) -> tuple[dict[str, Any], list[Event]]:
    """跑一次编排。带 token_pool+user_id 时前置 reserve；余额不足→quota_paused 中断。

    p6.3：`sink` 每产生一个事件同步回调一次（供 /tasks 实时转发队列）；
    不传则仅收集到返回的 events 列表（旧行为，测试依赖）。
    p6.5：`model` 指定本次对话模型（None→settings.llm_brain_model）。
    p7.1：`run_id` 可外部指定（暂停/续跑要按同一个 id 找到任务）；`cancel_event` 置位
    时在步骤边界协作式暂停，返回 status=paused_user。**取消/报错按预扣额 settle**
    （已发生的调用不退，避免"发起即暂停"套取退款；如实记账，不多退）。
    """
    rid = run_id or new_run_id()
    turn_id = new_run_id()
    emitter = RunEventEmitter(rid, turn_id)
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
        task_id=rid,
        should_cancel=should_cancel(cancel_event),
    )
    cfg = {"configurable": {"thread_id": rid}}
    init: dict[str, Any] = {
        "text": text,
        "run_id": rid,
        "turn_id": turn_id,
        "model": model,
        "effort": effort,
        "context_parts": context_parts or {"current": text},
        "raw_text": raw_text,
    }
    if user_id is not None:
        init["user_id"] = user_id
        init["estimate"] = estimate

    try:
        state = graph.invoke(init, cfg)
    except RunCancelled:
        # p7.1：用户主动暂停（协作式取消）——如实收尾，可按预扣额结算后从暂停列表续跑
        logger.info("任务被用户暂停 run_id=%s", rid)
        emit(emitter.content_delta("⏸ 已按你的要求暂停。本轮已产生的调用不退，可稍后点「继续」重跑。"))
        emit(emitter.done("paused_user", model=model_id))
        if token_pool is not None and user_id is not None:
            token_pool.settle(user_id, estimate, estimate, task_id=rid, model=model_id)  # 保守：不退
        return (
            {
                "run_id": rid,
                "thread_id": rid,
                "status": "paused_user",
                "route": None,
                "result": "（已按用户要求暂停）",
                # 与 settle(estimate) 一致：暂停任务记保守结算额，账实相符
                "tokens_used": estimate,
            },
            events,
        )
    except Exception as e:  # noqa: BLE001 - 编排崩溃也要给流一个体面的 done（前端能收尾）
        logger.exception("编排执行失败 run_id=%s", rid)
        # p7.1：中途报错也是"暂停"——保留任务与文字，让用户能一键重试（而不是从零再打一遍）
        emit(emitter.error(f"编排执行失败：{e}"))
        emit(emitter.done("paused_error", model=model_id))
        if token_pool is not None and user_id is not None:
            token_pool.settle(user_id, estimate, estimate, task_id=rid, model=model_id)  # 保守：不退
        return (
            {
                "run_id": rid,
                "thread_id": rid,
                "status": "paused_error",
                "route": None,
                "result": "",
                "error": str(e),
                "tokens_used": estimate,  # 同 paused_user：保守结算，账实相符
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
                "run_id": rid,
                "thread_id": rid,
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
            user_id, estimate, actual, task_id=rid,
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
            "run_id": rid,
            "thread_id": rid,
            "status": "done",
            "route": state.get("route"),
            "intents": state.get("intents", []),
            "score": state.get("score", 0.0),
            "primary_agent": state.get("primary_agent"),
            "dag": state.get("dag"),
            "tokens_used": int(state.get("tokens_used", 0)),
            "result": state.get("result", ""),
            "validation": state.get("validation"),
            "token_limit_reached": bool(state.get("token_limit_reached")),
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
