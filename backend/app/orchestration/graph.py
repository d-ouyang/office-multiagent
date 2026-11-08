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
from .checkpoints import get_checkpointer
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
    usage_steps: list               # p6.45：逐步用量明细（label+tokens），随 DONE/trace 给前端
    intent_source: str
    token_limit_reached: bool
    need_input: dict | None         # 2.1.0 P1-1：ask_user 载荷（question/options/need_file/file_hint）
    react_history: list             # 2.1.0 P1-1：已完成步骤回放（thought/action/input/observation）
    user_answer: str | None         # 2.1.0 P1-1：resume 注入的用户补充
    ask_count: int                  # 2.1.0 P1-1：ask_user 已触发次数（≥3 不再允许，防循环）


def _serialize_react_history(steps: list) -> list[dict[str, Any]]:
    """2.1.0 P1-1：Step → 可落库回放的 dict（thought/action/input/observation）。
    不保留 calls/call_id——续跑后这些步以观察文本形式进上下文（原 tool 消息
    已随上个进程结束，重放协议回填反而会造出没有配对 tool 消息的悬空 id）。"""
    out: list[dict[str, Any]] = []
    for st in steps or []:
        out.append(
            {
                "thought": str(getattr(st, "thought", "") or ""),
                "action": getattr(st, "action", None),
                "action_input": _json_safe_dict(getattr(st, "action_input", {}) or {}),
                "observation": str(getattr(st, "observation", "") or "")[:4000],
            }
        )
    return out


def _deserialize_react_history(rows: list[dict[str, Any]]) -> list:
    from .react import Step

    out: list = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append(
            Step(
                thought=str(row.get("thought") or ""),
                action=row.get("action"),
                action_input=dict(row.get("action_input") or {}),
                observation=str(row.get("observation") or "") or None,
            )
        )
    return out


def _json_safe_dict(value: Any) -> dict[str, Any]:
    import json as _json

    try:
        return _json.loads(_json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return {str(k): str(v) for k, v in (value or {}).items()}


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
        # 2.1.0 P1-1（HITL）：paused_input 续跑时回放已完成步骤 + 注入用户补充；
        # ask_count ≥ 3 后不再允许 ask_user（防问询循环），强制收敛给终答。
        ask_count = int(state.get("ask_count") or 0)
        prior_steps = _deserialize_react_history(state.get("react_history") or [])
        seed = str(state.get("user_answer") or "").strip() or None
        # 2.1.0：token 上限触达 → interrupt 暂停（用户可继续=预算重置 / 放弃本轮）。
        # 无 checkpointer 时不可暂停（中断后无法恢复=假挂起），回落收尾终答。
        budget_interrupt_fn = None
        if checkpointer is not None and token_budget is not None:
            def budget_interrupt_fn(payload: dict[str, Any]) -> str:
                return str(interrupt(payload) or "")

        res = run_react(
            state["text"],
            brain,
            spec_tools,
            emitter=emitter,
            emit=emit,
            should_cancel=should_cancel,
            token_budget=token_budget,
            prior_steps=prior_steps,
            seed_observation=seed,
            allow_ask_user=ask_count < 3,
            budget_interrupt=budget_interrupt_fn,
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
        # p6.45：逐步用量（规划 + ReAct 各步 + 外部用量），随 DONE/trace 给前端浮窗
        usage_steps = [{"label": "规划与决策", "tokens": int(state.get("planning_tokens", 0))}]
        usage_steps += list(getattr(res, "steps_usage", []) or [])
        # 2.1.0 P1-1：ask_user 触发——回放序列化 + 计数，交给 ask_pause 节点 interrupt
        if getattr(res, "need_input", None):
            return {
                "result": "",
                "tokens_used": billed,
                "usage_steps": usage_steps,
                "validation": validation,
                "token_limit_reached": token_budget.limit_reached,
                "need_input": dict(res.need_input),
                "react_history": _serialize_react_history(res.steps),
                "ask_count": ask_count + 1,
            }
        return {
            "result": res.final,
            "tokens_used": billed,
            "usage_steps": usage_steps,
            "validation": validation,
            "token_limit_reached": token_budget.limit_reached,
            # 显式清除：TypedDict 合并只覆盖返回的键——残留旧 need_input 会让
            # ask_gate 在终答后再次进 ask_pause（实测踩过）
            "need_input": None,
            "user_answer": None,
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
        synth_tokens = 0
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
            synth_tokens = int(usage.get("total_tokens", 0))
            total_tokens += synth_tokens
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
        # p6.45：multi 的逐步用量 = 规划 + 各子任务 + 汇总官
        usage_steps = [{"label": "规划与决策", "tokens": int(state.get("planning_tokens", 0))}]
        usage_steps += [
            {"label": f"子任务·{key}", "tokens": int(getattr(r, "tokens_used", 0) or 0)}
            for key, r in results.items()
        ]
        usage_steps.append({"label": "汇总官整合", "tokens": synth_tokens})
        return {
            "result": final_text,
            "tokens_used": total_tokens,
            "usage_steps": usage_steps,
            "validation": validations or None,
            "token_limit_reached": token_budget.limit_reached,
        }

    g = StateGraph(TaskState)
    g.add_node("planner", planner_node)
    g.add_node("single", single_node)
    g.add_node("multi", multi_node)
    g.add_conditional_edges("planner", route_edge, {"single": "single", "multi": "multi"})
    # 2.1.0 P1-1（HITL）：single 完成后若带 need_input → ask_pause 节点 interrupt()
    # 挂起等用户（checkpoint 落档）；resume 注入回答后回到 single，从回放观察继续。
    # ask_pause 节点零副作用，重入安全（interrupt 语义要求）。
    def ask_pause_node(state: TaskState) -> dict[str, Any]:
        payload = dict(state.get("need_input") or {})
        answer = interrupt({"type": "ask_user", **payload})
        return {"user_answer": str(answer or "").strip()}

    def ask_gate(state: TaskState) -> str:
        return "ask_pause" if state.get("need_input") else "end"

    g.add_node("ask_pause", ask_pause_node)
    g.add_conditional_edges("single", ask_gate, {"ask_pause": "ask_pause", "end": END})
    g.add_edge("ask_pause", "single")
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

    checkpointer = get_checkpointer() if token_pool is not None else None
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
        if payload.get("type") == "budget_paused":
            # 2.1.0：token 上限暂停——用户可继续（预算重置）或放弃本轮
            ask_payload = {k: v for k, v in payload.items() if k != "type"}
            emit(emitter.observation("budget_paused", f"已达单任务 token 上限 {payload.get('limit')}，已暂停等待你的选择"))
            emit(emitter.done("paused_budget", model=model_id))
            if token_pool is not None and user_id is not None:
                token_pool.settle(user_id, estimate, estimate, task_id=rid, model=model_id)  # 保守：不退
            _register_live_checkpointer(rid, checkpointer)
            return (
                {
                    "run_id": rid,
                    "thread_id": rid,
                    "status": "paused_budget",
                    "route": state.get("route"),
                    "result": "",
                    "pause_payload": {"budget": ask_payload, "replay": state.get("react_history") or []},
                    "estimate": estimate,
                    "tokens_used": int(state.get("tokens_used", 0) or 0),
                },
                events,
            )
        if payload.get("type") == "ask_user":
            # 2.1.0 P1-1（HITL）：模型请求补充输入——任务转 paused_input，
            # checkpoint 已由 interrupt 落档；graph 实例登记供同进程续跑。
            ask = {k: v for k, v in payload.items() if k != "type"}
            emit(emitter.ask_user(**ask))
            emit(emitter.done("paused_input", model=model_id))
            if token_pool is not None and user_id is not None:
                token_pool.settle(user_id, estimate, estimate, task_id=rid, model=model_id)  # 保守：不退
            _register_live_checkpointer(rid, checkpointer)
            return (
                {
                    "run_id": rid,
                    "thread_id": rid,
                    "status": "paused_input",
                    "route": state.get("route"),
                    "result": "",
                    "ask": ask,
                    "react_history": state.get("react_history") or [],
                    "pause_payload": {
                        "ask": ask,
                        "replay": state.get("react_history") or [],
                    },
                    "tokens_used": int(state.get("tokens_used", 0) or 0),
                },
                events,
            )
        _register_live_checkpointer(rid, checkpointer)
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
                "estimate": estimate,  # 2.1.0：真续跑结算要退预扣，预扣额随 pause_payload 落库
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
            steps=state.get("usage_steps") or None,  # p6.45：逐步用量明细
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
    """充值后续跑：对同一 graph + thread_id 发 Command(resume=True)。

    p5.4：续跑前**显式校验存档存在**。探针实测（langgraph 1.2.16）：对没有存档的
    thread 发 `Command(resume=True)`，LangGraph 不报错，而是**静默从头重跑**——
    持久化一旦失效，就会退化成重复执行已完成节点、重复计费，且没有任何告警。
    因此这里先 `get_state` 确认确有挂起点，否则明确抛错，把问题暴露在续跑之前。
    """
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = graph.get_state(cfg)
    if snap is None or not getattr(snap, "next", None):
        raise ValueError(
            f"没有可续跑的挂起任务（thread_id={thread_id}）：存档不存在或该任务已结束。"
            "请检查 checkpointer_backend 配置与存档是否仍在。"
        )
    state = graph.invoke(Command(resume=True), cfg)
    emit(emitter.done(state.get("route", "single")))
    return state


# --------------------------------------------------------------------------- #
# 2.1.0 P1-1（HITL）：paused_input 任务的续跑
# --------------------------------------------------------------------------- #

_LIVE_CHECKPOINTERS: dict[str, Any] = {}
_LIVE_CHECKPOINTERS_LOCK = threading.Lock()


def _register_live_checkpointer(run_id: str, checkpointer: Any) -> None:
    """暂停任务登记 checkpointer 实例（memory 后端的存档跟着实例走）。

    续跑时重建 graph（事件绑新流）+ 复用该 checkpointer——graph 实例本身
    不能复用：它的事件回调闭包绑着创建时的流，重建后旧流早关了。
    sqlite 后端存档在盘上，无需登记也能找回。上限 200 防泄漏。"""
    with _LIVE_CHECKPOINTERS_LOCK:
        if len(_LIVE_CHECKPOINTERS) >= 200:
            _LIVE_CHECKPOINTERS.pop(next(iter(_LIVE_CHECKPOINTERS)))
        _LIVE_CHECKPOINTERS[run_id] = checkpointer


def _take_live_checkpointer(run_id: str) -> Any | None:
    with _LIVE_CHECKPOINTERS_LOCK:
        cp = _LIVE_CHECKPOINTERS.get(run_id)
        return cp  # peek 语义：resume 失败时仍保留，重试可再取


def _forget_live_checkpointer(run_id: str) -> None:
    with _LIVE_CHECKPOINTERS_LOCK:
        _LIVE_CHECKPOINTERS.pop(run_id, None)


def resume_with_answer(
    run_id: str,
    answer: str,
    *,
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
    token_pool: TokenPool | None = None,
    user_id: int | None = None,
    model: str | None = None,
    effort: str | None = None,
    username: str | None = None,
) -> tuple[dict[str, Any], list[Event]]:
    """用户补充输入后断点续跑：Command(resume=answer) 回到 ask_pause 节点。

    p5.4 铁律：先 get_state 校验存档存在（无存档时 Command(resume) 会静默
    从头重跑而非报错——重复执行已完成节点、重复计费且无告警）。
    graph 实例优先取进程内登记表；memory 后端 + 进程重启后拿不到 → 明确报错
    （提示配 sqlite 或重新发起任务）。"""
    events: list[Event] = []

    def emit2(ev: Event) -> None:
        events.append(ev)
        emit(ev)

    # 续跑一律重建 graph（事件绑新流）；checkpointer 取登记实例（memory）或
    # sqlite 共享单例——存档跟着 checkpointer 走，不跟 graph 实例走。
    backend = (settings.checkpointer_backend or "memory").strip().lower()
    checkpointer = _take_live_checkpointer(run_id)
    if checkpointer is None and backend == "sqlite":
        checkpointer = get_checkpointer()
    if checkpointer is None:
        raise ValueError(
            f"暂停任务的存档已失效（run_id={run_id}）：memory 后端不支持跨重启续跑，"
            "请配置 CHECKPOINTER_BACKEND=sqlite，或重新发起任务并在附件里带上补充材料。"
        )
    # model/effort 不传——build_graph 无此参数，且 checkpoint 里的 TaskState 已含原值
    graph = build_graph(
        emitter,
        emit2,
        token_pool=token_pool,
        checkpointer=checkpointer,
        username=username,
        user_id=user_id,
        task_id=run_id,
        should_cancel=None,
    )
    cfg = {"configurable": {"thread_id": run_id}}
    snap = graph.get_state(cfg)
    if snap is None or not getattr(snap, "next", None):
        raise ValueError(
            f"没有可续跑的挂起任务（thread_id={run_id}）：存档不存在或该任务已结束。"
        )
    state = graph.invoke(Command(resume=str(answer or "").strip()), cfg)
    actual = int(state.get("tokens_used", 0) or 0)
    if token_pool is not None and user_id is not None:
        token_pool.settle(user_id, 0, actual, task_id=run_id, model=state.get("model") or model)
    route = state.get("route", "single")
    if state.get("need_input"):
        # 续跑后模型又发起了一轮 ask_user——保持 paused_input，graph 重新登记
        ask = dict(state.get("need_input") or {})
        emit2(emitter.ask_user(**ask))
        emit2(emitter.done("paused_input", model=state.get("model") or model))
        _register_live_checkpointer(run_id, checkpointer)
        return (
            {
                "run_id": run_id,
                "thread_id": run_id,
                "status": "paused_input",
                "route": route,
                "result": "",
                "ask": ask,
                "react_history": state.get("react_history") or [],
                "tokens_used": actual,
            },
            events,
        )
    _forget_live_checkpointer(run_id)
    emit2(
        emitter.done(
            route,
            tokens_used=actual,
            model=state.get("model") or model,
            steps=state.get("usage_steps") or None,
        )
    )
    return (
        {
            "run_id": run_id,
            "thread_id": run_id,
            "status": "done",
            "route": route,
            "intents": state.get("intents", []),
            "primary_agent": state.get("primary_agent"),
            "dag": state.get("dag"),
            "tokens_used": actual,
            "result": state.get("result", ""),
            "validation": state.get("validation"),
            "token_limit_reached": bool(state.get("token_limit_reached")),
        },
        events,
    )
