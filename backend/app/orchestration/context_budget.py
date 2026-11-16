"""ReAct 历史的上下文预算器（v2.3.0-p1.1）。

为什么存在：p6.9 把四条截断链路放大到 24000 字之后，历史占用变成"每步 24K × 步数"，
没有任何总量约束——4~5 步就能顶到 128K 窗口，而 provider 的 context_length 400
不在 llm.py 的兜底范围（p1.2 才补）。本模块把"渲染历史"从"逐条截断"改成"按预算分配"。

规则（与 rag core/context_budget.py 同构，差异是**降级而非丢弃**：观察里的数字是
终答的依据，整块丢掉比压成要点更危险）：

  · 保序：最近的步骤优先保留原文（模型下一步最依赖它）；
  · 整块降级：旧步压成"调用了 X，返回 N 行，要点…"，绝不切半句；
  · 末步保底：最后一步即使自身超预算也保留（截断并标注）；
  · seed 步免疫：无工具调用的步（HITL 用户补充输入）不可再生，永远保留；
  · 双协议同源：返回 `obs_text`（每步最终观察文本），JSON 与原生 tool_calls 共用同一份判定；
  · 可观测：返回 downgraded/omitted/dropped_chars，调用方写 context_usage 事件；
  · 0 = 不限：回退开关，行为回到 v2.3.0-p1.0 的逐条截断。

为什么不做 LLM 摘要压缩：成本双倍（要再调一次模型），且当前没有能测"压缩后准确率"
的门禁——等 golden set 扩容后再议（PLAN-2.3.0 §6）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .memory import estimate_tokens

#: 单块超长时的保底字符数（再小就连"调用了什么"都看不出来）
_MIN_LINE_CHARS = 80


@dataclass
class BudgetResult:
    """一次预算渲染的结果。

    `lines` 是 JSON 协议直接拼进提示词的文本；`obs_text` 是 1-based 步号 → 该步最终
    观察文本（原文或降级文案），供原生 tool_calls 协议按消息结构复用——两条协议必须
    吃到同一份判定，否则灰度期换协议就换行为。
    """

    lines: list[str] = field(default_factory=list)
    obs_text: dict[int, str] = field(default_factory=dict)
    kept: int = 0            # 原文保留的步数
    downgraded: int = 0      # 压成摘要的步数
    omitted: int = 0         # 整块省掉的步数（预算实在不够）
    dropped_chars: int = 0   # 因降级/截断丢失的字符数
    budget: int = 0          # 本次预算（token），0=不限
    notes: list[str] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return self.downgraded > 0 or self.omitted > 0

    def summary_note(self) -> str:
        if not self.truncated:
            return ""
        return (
            f"上下文预算 {self.budget}：原文 {self.kept} 步、降级 {self.downgraded} 步、"
            f"省略 {self.omitted} 步（丢弃约 {self.dropped_chars} 字）"
        )


def _obs_body(st: Any, step_cap: int) -> str:
    """一步的观察正文（按 step_cap 截断并标注）。step_cap=0 表示不截。"""
    obs = getattr(st, "observation", None)
    if obs is None:
        return ""
    text = str(obs)
    if step_cap > 0 and len(text) > step_cap:
        return text[:step_cap] + "…（已截断）"
    return text


def _full_line(idx: int, st: Any, body: str) -> str:
    """JSON 协议的完整行：编号 + 思考 + 动作 + 观察。"""
    line = f"{idx}. 思考：{getattr(st, 'thought', '') or '（无）'}"
    action = getattr(st, "action", None)
    if action:
        args = getattr(st, "action_input", {}) or {}
        line += f" | 动作：{action}({json.dumps(args, ensure_ascii=False, default=str)})"
    if getattr(st, "observation", None) is not None:
        line += f" | 观察：{body}"
    return line


def _digest_body(st: Any, digest_chars: int) -> str:
    """降级文案：工具名 + 参数个数 + 返回行数 + 开头要点。

    为什么保留"返回 N 行"：模型据此判断"这份数据够不够答"，比只看到一段截断文本
    更能决定下一步是补查还是收尾。
    """
    action = getattr(st, "action", None) or "（无动作）"
    args = getattr(st, "action_input", {}) or {}
    obs = str(getattr(st, "observation", "") or "")
    rows = (obs.count("\n") + 1) if obs else 0
    head = " ".join(obs.split())[:digest_chars]
    tail = f"…（原文 {len(obs)} 字）" if len(obs) > digest_chars else ""
    arg_note = f"，{len(args)} 个参数" if args else ""
    return f"调用了 {action}{arg_note}，返回 {rows} 行：{head}{tail}"


def _cap_line(line: str, max_tokens: int) -> str:
    keep = max(_MIN_LINE_CHARS, int(max_tokens) - 20)
    if len(line) <= keep:
        return line
    return line[:keep] + "…（超长截断）"


def budget_steps(
    steps: list[Any],
    max_tokens: int,
    *,
    step_cap: int = 0,
    digest_chars: int = 200,
) -> BudgetResult:
    """按 token 预算渲染历史步骤。

    max_tokens <= 0 → 不限，逐条截断（与 v2.3.0-p1.0 行为一致，作为回退路径）。
    step_cap 是单步字符上限（0=不限），先于预算生效——每步先不炸，再谈总量。
    """
    total = len(steps)
    if total == 0:
        return BudgetResult(budget=max(0, int(max_tokens)))

    bodies = [_obs_body(st, step_cap) for st in steps]
    full_lines = [
        _full_line(i, st, bodies[i - 1]) for i, st in enumerate(steps, 1)
    ]

    if max_tokens <= 0:
        return BudgetResult(
            lines=full_lines,
            obs_text={i: bodies[i - 1] for i in range(1, total + 1)},
            kept=total,
            budget=0,
        )

    # 常见路径：全文装得下就原样返回，别给小任务平白加摘要噪音
    if sum(estimate_tokens(line) for line in full_lines) <= max_tokens:
        return BudgetResult(
            lines=full_lines,
            obs_text={i: bodies[i - 1] for i in range(1, total + 1)},
            kept=total,
            budget=max_tokens,
        )

    lines_rev: list[str] = []
    obs_rev: dict[int, str] = {}
    used = 0
    kept = downgraded = dropped_chars = 0
    digest_mode = False
    omitted = 0

    for idx in range(total - 1, -1, -1):  # 从最近一步往回装
        number = idx + 1
        st = steps[idx]
        is_seed = getattr(st, "action", None) is None

        if is_seed:
            # 用户补充输入（HITL seed）不可再生：预算再紧也保留，只截正文。
            # 最多吃掉"剩余预算 − 30"，给更早的降级行留一口气，避免把别人挤光。
            body = bodies[idx]
            line = _full_line(number, st, body)
            remaining = max_tokens - used
            if estimate_tokens(line) > remaining:
                share = max(_MIN_LINE_CHARS, remaining - 30)
                body = _cap_line(body, share)
                line = _full_line(number, st, body)
            used += estimate_tokens(line)
            lines_rev.append(line)
            obs_rev[number] = body
            kept += 1
            continue

        if not digest_mode:
            line = full_lines[idx]
            cost = estimate_tokens(line)
            if used + cost <= max_tokens or not lines_rev:
                if used + cost > max_tokens:
                    # 末步保底：自己就超预算 → 截断后保留，但最多吃掉 60% 预算——
                    # 否则"最近优先"退化成"最近独吞"，前面所有历史被整块省略。
                    share = max_tokens if total == 1 else max(1, int(max_tokens * 0.6))
                    body = _cap_line(bodies[idx], share)
                    capped = _full_line(number, st, body)
                    dropped_chars += len(bodies[idx]) - len(body)
                    line, cost, bodies[idx] = capped, estimate_tokens(capped), body
                used += cost
                lines_rev.append(line)
                obs_rev[number] = bodies[idx]
                kept += 1
                continue
            digest_mode = True  # 再往前的步一律降级

        digest = _digest_body(st, digest_chars)
        line = f"{number}. {digest}"
        cost = estimate_tokens(line)
        if used + cost <= max_tokens:
            used += cost
            lines_rev.append(line)
            obs_rev[number] = digest
            downgraded += 1
            dropped_chars += max(
                0, len(str(getattr(st, "observation", "") or "")) - digest_chars
            )
            continue
        # 连摘要都放不下：从这里开始整块省略
        omitted = number
        break

    lines = list(reversed(lines_rev))
    if omitted:
        lines.insert(0, f"（更早 {omitted} 步已省略）")

    result = BudgetResult(
        lines=lines,
        obs_text=obs_rev,
        kept=kept,
        downgraded=downgraded,
        omitted=omitted,
        dropped_chars=dropped_chars,
        budget=max_tokens,
    )
    if result.truncated:
        result.notes.append(result.summary_note())
    return result
