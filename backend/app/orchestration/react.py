"""单 Agent ReAct 循环（p4.1）——设计文档 §四.4：Thought → Action → Observation 至终答，
max_iterations 防跑飞，超限强制给阶段结论。Brain 可插拔（确定性基线 / 未来 LLM，§12.5 接口化）。
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.events import Event, RunEventEmitter
from ..core.runs import RunCancelled
from ..core.token_budget import TaskTokenBudget, TokenLimitReached
from .tools import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """去掉 NaN，保证 visual 事件能写成 JSON。"""
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class Step:
    thought: str = ""
    action: str | None = None       # 工具名；None 表示本步直接给终答
    action_input: dict[str, Any] = field(default_factory=dict)
    observation: str | None = None
    final: str | None = None        # 非 None = 终答，循环结束
    streamed: bool = False          # p6.3：终答已由 brain 逐字推过（run_react 不重复整段发）
    invalid_action: bool = False    # p6.7：action 是无效工具名（LLM 幻觉，如 "none"）
    chunked: bool = False           # p6.7：终答需由 run_react 切片推（JSON 包装的 final）
    # v2.0.0-p1.4：原生 tool_calls 扩展。calls 非空 = 本轮模型要求调用多个工具，
    # run_react 串行展开成多个"动作单元"逐步执行（与 DAG 线程池并行是两层事）。
    calls: list[dict[str, Any]] = field(default_factory=list)
    call_id: str | None = None      # 单个 call 的原生 id（历史回填 tool_call_id 用）
    parse_error: str | None = None  # p1.2 落下的 arguments 解析错误（该 call 不真执行）


def _summarize_observation(obs: Any, *, max_chars: int = 24000) -> str:
    """p6.7：工具结果进 LLM 上下文的可读摘要——不是 str(dict) 全文。
    p6.9：content 截断 1200 → 24000（read_document max_chars 同步 50000，
    "通读整篇"场景 2 万字文档全量进上下文；deepseek-chat 128K 装得下）。

    原实现把含 8000 字 content 的 dict repr 原样塞进 history，LLM 下一轮上下文
    被垃圾撑爆（真跑见证：read_document 成功后 LLM 幻觉出 action="none"）。
    现在：dict 取关键字段、content 截断、截断如实标注。
    """
    if isinstance(obs, dict):
        parts = []
        for key, value in obs.items():
            if key == "content" and isinstance(value, str):
                shown = value[:max_chars]
                tail = (
                    f"…（原文共 {obs.get('total_chars', len(value))} 字，已截断展示）"
                    if len(value) > max_chars
                    else ""
                )
                parts.append(f"content={shown}{tail}")
                continue
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            if len(rendered) > 8000:
                rendered = rendered[:8000] + "…（已截断）"
            parts.append(f"{key}={rendered}")
        text = "；".join(parts)
    else:
        text = str(obs)
    return text[:max_chars * 2]


def _same_call(left: Step, name: str, action_input: dict[str, Any]) -> bool:
    if left.action != name or left.observation is None:
        return False
    return json.dumps(left.action_input, sort_keys=True, ensure_ascii=False, default=str) == json.dumps(
        action_input, sort_keys=True, ensure_ascii=False, default=str
    )


class Brain(Protocol):
    """决策脑：给定任务与历史，产出下一步（调工具 or 给终答）。"""

    def next_step(self, task: str, history: list[Step]) -> Step: ...


@dataclass
class AgentResult:
    final: str
    steps: list[Step]
    iterations: int
    hit_cap: bool = False
    tokens_used: int = 0       # p4.3c：本次 ReAct 的真实 LLM 用量（brain.usage 汇总；StubBrain 为 0）
    external_tokens: int = 0   # 外部工具（知识库检索）带回的 token，并入办公侧结算
    assets: list[dict[str, str]] = field(default_factory=list)  # p6.30：过程产出的文件/数据资产（file_name 等）
    steps_usage: list[dict[str, Any]] = field(default_factory=list)  # p6.45：逐步用量（label+tokens），随 DONE/trace 给前端
    need_input: dict[str, Any] | None = None  # 2.1.0 P1-1：ask_user 触发——任务转 paused_input，等用户补充后断点续跑


class StubBrain:
    """确定性基线 brain：一步"思考 + 终答"，不调 LLM（供闭环跑通与测试）。

    真实 LLM brain（DeepSeek/Qwen，§四.4 的 Thought/Action 生成）后续按 Brain 协议插入。
    """

    def __init__(self, answer: str) -> None:
        self.answer = answer

    def next_step(self, task: str, history: list[Step]) -> Step:
        return Step(thought=f"理解任务：{task[:40]}", final=self.answer)


def run_react(
    task: str,
    brain: Brain,
    tools: ToolRegistry,
    *,
    max_iterations: int = 10,
    emitter: RunEventEmitter | None = None,
    emit: Callable[[Event], None] | None = None,
    synthesize: Callable[[str, list[Step]], str] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    token_budget: TaskTokenBudget | None = None,
    prior_steps: list["Step"] | None = None,
    seed_observation: str | None = None,
    allow_ask_user: bool = False,
) -> AgentResult:
    """跑 ReAct 循环；超 max_iterations 强制给阶段结论（§四.4 防跑飞）。

    p4.3d：`synthesize(reason, history)`——被护栏强制停止时（重复调用/无效工具名/超步数），
    用它把「已有观察」收尾成面向用户的结论。此前护栏直接把内部提示原文当终答，
    用户看到的是"已有工具结果，停止重复调用…"这类机器话（真跑见证）。不传则回落原文。

    p7.1：`should_cancel()`——每一步开始前检查；命中即抛 `RunCancelled`（协作式取消），
    由 run_task 收尾为 paused_user。检查点放在【LLM 调用之前】，保证暂停最多多跑一步。

    2.1.0 P1-1（HITL）：`prior_steps` + `seed_observation`——paused_input 续跑时
    把已完成步骤的观察回放进 history（副作用零重跑），并把用户补充输入作为最后一条
    观察注入；`allow_ask_user`——模型调 ask_user 时是否允许暂停（single=True；
    multi 子任务层内并行无法安全暂停，False 时给"无法中途确认"的替代观察继续循环）。
    """
    history: list[Step] = list(prior_steps or [])  # 2.1.0 P1-1：续跑时回放已完成步骤（观察进上下文，副作用零重跑）
    if seed_observation:
        history.append(
            Step(thought="", observation=f"用户已补充输入：{seed_observation}")
        )
    invalid_streak = 0  # p6.7：连续无效工具名计数（幻觉兜底）
    assets: list[dict[str, str]] = []  # p6.30：产出资产（下游子任务要能拿到文件名/id，不只文本摘要）
    external_tokens = 0

    def _emit(ev: Event) -> None:
        if emit is not None:
            emit(ev)

    def _cap_final(reason: str, fallback: str) -> str:
        """护栏收尾：优先让模型基于已有观察写人话；失败回落原文（不阻断、不编造）。"""
        if synthesize is None:
            return fallback
        try:
            text = (synthesize(reason, list(history)) or "").strip()
            return text or fallback
        except Exception:  # noqa: BLE001 - 收尾失败不阻断任务，如实回落
            logger.exception("强制收尾失败（回落原文）reason=%s", reason)
            return fallback

    steps_usage: list[dict[str, Any]] = []  # p6.45：逐步用量（label+tokens），随 DONE/trace 给前端

    for i in range(1, max_iterations + 1):
        if should_cancel is not None and should_cancel():
            # p7.1：用户主动暂停——在 LLM 调用之前退出，最多多花一步
            raise RunCancelled("用户暂停")
        tokens_before = int(getattr(brain, "usage", {}).get("total_tokens", 0) or 0)
        try:
            step = brain.next_step(task, history)
        except TokenLimitReached:
            done_steps = [item for item in history if item.observation]
            cap = (
                f"本次任务已达到全局 token 上限 {token_budget.limit if token_budget else ''}，"
                f"已在模型调用边界停止。已完成 {len(done_steps)} 个工具步骤；"
                "已有结果保留，未完成部分请拆成下一次任务继续。"
            )
            if emitter is not None:
                _emit(emitter.observation("token_limit", cap))
                _emit(emitter.content_delta(cap))
            return AgentResult(
                final=cap,
                steps=history,
                iterations=i,
                hit_cap=True,
                assets=assets,
                external_tokens=external_tokens,
                steps_usage=steps_usage,
            )
        # p6.45：逐步用量采样——brain.usage 每次调用后累计，差值即本步 LLM 消耗
        step_delta = int(getattr(brain, "usage", {}).get("total_tokens", 0) or 0) - tokens_before
        if step_delta > 0:
            if step.final is not None:
                label = "生成终答"
            elif getattr(step, "calls", None):
                label = f"调用 {len(step.calls)} 个工具"
            else:
                label = f"调用 {step.action}"
            steps_usage.append({"label": f"第{i}步·{label}", "tokens": step_delta})

        if emitter is not None and step.thought:
            _emit(emitter.thinking_delta(step.thought))

        if step.final is not None:
            # p6.3：brain 已逐字推过（streamed）则只记录，不再整段重发
            # p6.7：JSON 包装的终答（chunked）按 5 字/块切片推——视觉等同打字机
            if emitter is not None:
                if getattr(step, "chunked", False):
                    text = step.final
                    for k in range(0, len(text), 5):
                        _emit(emitter.content_delta(text[k:k + 5]))
                        time.sleep(0.012)
                elif not step.streamed:
                    _emit(emitter.content_delta(step.final))
            history.append(step)
            return AgentResult(final=step.final, steps=history, iterations=i, assets=assets, external_tokens=external_tokens, steps_usage=steps_usage)

        # v2.0.0-p1.4：tool_calls 多 call → 串行展开为动作单元；json 路径 = 单元即本步。
        # （先串行执行降风险：与 DAG 线程池并行是两层事，勿混配额/取消语义。）
        if getattr(step, "calls", None):
            units: list[Step] = []
            for idx, call in enumerate(step.calls):
                units.append(
                    Step(
                        thought=step.thought if idx == 0 else "",
                        action=str(call.get("name") or ""),
                        action_input=call.get("arguments") or {},
                        call_id=str(call.get("id") or "") or None,
                        parse_error=call.get("parse_error"),
                    )
                )
        else:
            units = [step]

        for unit in units:
            name = unit.action or ""
            tool_id = unit.call_id or name  # tool_calls 路径用原生 id；json 路径保持 name

            if unit.parse_error:
                # p1.2/p1.4 红线：arguments 解析失败不抛崩整图——回工具错误观察，该 call 不真执行
                obs_text = f"工具参数解析失败：{unit.parse_error}（本次未执行）。请修正参数后重试，或直接写最终回答。"
                if emitter is not None:
                    _emit(emitter.tool_call_start(tool_id, name, unit.action_input))
                    _emit(emitter.observation(tool_id, obs_text))
                    _emit(emitter.tool_call_end(tool_id, name, success=False, error=unit.parse_error))
                unit.observation = obs_text[:500]
                history.append(unit)
                continue

            if getattr(unit, "invalid_action", False):
                # p6.7：LLM 幻觉出无效工具名（如 "none"）——不真调工具，给纠错观察；
                # 连续 2 次无效 → 强制如实收尾（过程透明，不空转）。
                invalid_streak += 1
                hint = f"无效工具名 {name!r}；可用工具：{list(tools.names())}。任务已完成时请直接写自然语言终答。"
                if emitter is not None:
                    _emit(emitter.observation(name, hint))
                unit.observation = hint
                history.append(unit)
                if invalid_streak >= 2:
                    done_steps = [s for s in history if s.observation]
                    cap = (
                        f"模型连续给出无效工具名，已强制停止。已完成：{len(done_steps)} 步"
                        f"（如 " + "、".join(s.action or "?" for s in done_steps[-3:]) + "）。"
                        "请检查可用工具列表后重试，或换一种问法。"
                    )
                    cap = _cap_final("模型连续给出无效工具名", cap)
                    if emitter is not None:
                        _emit(emitter.content_delta(cap))
                    return AgentResult(final=cap, steps=history, iterations=i, hit_cap=True, assets=assets, external_tokens=external_tokens, steps_usage=steps_usage)
                continue

            prior = [s for s in history if _same_call(s, name, unit.action_input)]
            if prior:
                previous = prior[-1].observation or ""
                unit.observation = (
                    "相同参数已经调用过，请直接基于已有观察写最终回答，不要再次调用。"
                    f"上次观察：{previous[:4000]}"
                )
                history.append(unit)
                if len(prior) >= 2:
                    final = "已有工具结果，停止重复调用。请根据下面的观察作答，不要编造。\n" + previous[:4000]
                    final = _cap_final("模型对同一工具重复调用相同参数", final)
                    if emitter is not None:
                        _emit(emitter.content_delta(final))
                    return AgentResult(final=final, steps=history, iterations=i, hit_cap=True, assets=assets, external_tokens=external_tokens, steps_usage=steps_usage)
                continue

            if emitter is not None:
                _emit(emitter.tool_call_start(tool_id, name, unit.action_input))
            res: ToolResult = tools.call(name, **unit.action_input)
            obs = res.output if res.ok else (res.error or "工具调用失败")
            # 2.1.0 P1-1（HITL）：ask_user sentinel——模型请求用户补充输入。
            # single（allow_ask_user=True）→ 发 ask_user 事件并终止本轮，任务转
            # paused_input（graph 层 interrupt 落 checkpoint）；multi 层内并行无法
            # 安全暂停，给替代观察让模型继续循环。
            if res.ok and isinstance(obs, dict) and obs.get("__ask_user__"):
                questions = obs.get("questions")
                if not isinstance(questions, list) or not questions:
                    questions = [
                        {
                            "question": str(obs.get("question") or ""),
                            "options": list(obs.get("options") or []),
                            "need_file": bool(obs.get("need_file")),
                            "file_hint": str(obs.get("file_hint") or ""),
                        }
                    ]
                ask = {"questions": questions}
                if not allow_ask_user:
                    unit.observation = (
                        "当前为多任务协作流程，无法中途向用户确认。"
                        "请基于已有信息继续完成任务；确实缺少必要材料时，"
                        "在最终回答里明确列出需要用户提供什么。"
                    )
                    history.append(unit)
                    continue
                unit.observation = f"已向用户发起补充输入请求：{ask['questions'][0]['question']}"
                history.append(unit)
                if emitter is not None:
                    _emit(emitter.ask_user(**ask))
                return AgentResult(
                    final="",
                    steps=history,
                    iterations=i,
                    assets=assets,
                    external_tokens=external_tokens,
                    steps_usage=steps_usage,
                    need_input=ask,
                )
            if emitter is not None and res.ok and isinstance(res.output, dict) and res.output.get("file_name"):
                _emit(
                    emitter.artifact(
                        str(res.output.get("doc_id") or res.output.get("export_id") or name),
                        str(res.output.get("format") or "file"),
                        str(res.output["file_name"]),
                        str(res.output.get("display_name") or res.output["file_name"]),
                    )
                )
            # p6.30：把文件产物记进 assets（file_name/export_id/clean_id）——multi 链路上
            # 下游子任务靠它引用上游文件（画图/嵌图），不再"只有文字没有数据"。
            if res.ok and isinstance(res.output, dict) and res.output.get("file_name"):
                asset = {
                    "tool": name,
                    "file_name": str(res.output["file_name"]),
                    "display_name": str(res.output.get("display_name") or res.output["file_name"]),
                }
                for key in ("export_id", "clean_id", "doc_id", "png_file"):
                    if res.output.get(key):
                        asset[key] = str(res.output[key])
                if not any(a["file_name"] == asset["file_name"] for a in assets):
                    assets.append(asset)
            if res.ok and isinstance(res.output, dict):
                usage = res.output.get("usage")
                if isinstance(usage, dict):
                    added = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
                    external_tokens += added
                    if added > 0:
                        steps_usage.append({"label": f"外部用量·{name}", "tokens": added})
                    if token_budget is not None:
                        token_budget.consume_external(added)
                visual = res.output.get("visual")
                if emitter is not None and isinstance(visual, dict):
                    _emit(emitter.visual(str(visual.get("kind") or "flow"), _json_safe(visual)))
            if emitter is not None:
                panel = obs
                if isinstance(obs, dict) and "visual" in obs:
                    panel = {key: value for key, value in obs.items() if key != "visual"}
                    panel["visual"] = "已交给界面绘制"
                # 前端步骤面板展示口径（p6.9：500 → 2000，用户能看到更多过程细节）
                _emit(emitter.observation(tool_id, str(panel)[:2000]))
                _emit(
                    emitter.tool_call_end(
                        tool_id, name, success=res.ok, error=None if res.ok else (res.error or "")
                    )
                )
            # p6.7：进 history 的是可读摘要（不是 str(dict) 全文），LLM 上下文卫生
            unit.observation = _summarize_observation(obs) if res.ok else str(obs)[:500]
            history.append(unit)

    # 超限：强制阶段结论（不硬编答案，只如实说明已达上限）
    cap = f"已达 max_iterations={max_iterations}，强制给出阶段结论"
    cap = _cap_final("达到最大步数上限", cap)
    if emitter is not None:
        _emit(emitter.content_delta(cap))
    return AgentResult(
        final=cap, steps=history, iterations=max_iterations, hit_cap=True,
        assets=assets, external_tokens=external_tokens, steps_usage=steps_usage,
    )
