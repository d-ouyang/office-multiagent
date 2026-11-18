"""会话记忆：近期原文 + 更早轮次的结构化摘要 + 指代对齐（v2.4.2 重写）。

旧实现（≤v2.4.1）把每轮问答切到 80 字当"摘要"：730 字的回答被砍成 "- 时…" 这种断句，
结尾「需要我导出成文档吗」直接丢失，用户回「需要」时模型无从对上。
更糟的是那块叫【历史摘要】的内容，用的是同一个切片函数——名字是摘要，行为是切片。

现在三层：
  1. 更早轮次 → **结构化摘要**（结论 / 数字 / 产物 / 未决问题），见 `summary.py`；
  2. 最近 N 轮 → **原文**，不截断（4 轮 ≈ 4000 token，占 1M 窗口 0.4%，没有省的必要）；
  3. 本轮问题 → 原文。

超预算时按降级链裁剪：丢最老整轮（丢的即时生成摘要）→ 仍超继续丢 → **最近 2 轮永不丢**。
指代对齐不靠代词词表（「需要/继续/你看着办」无法穷举），而是看上一轮有没有悬着的提问。
"""
from __future__ import annotations

import re
from typing import Any

from .summary import extract_open_questions, render_summary, summarize_round

RECENT_ROUNDS = 8
#: 保留的原义：当前句含这些词时补一句消解提示（次要手段，主手段见【待确认】块）
_PRONOUNS = ("这个", "那个", "它", "他", "她", "刚才", "上面", "上述", "这份", "该表", "该报表")
_CJK = re.compile(r"[\u4e00-\u9fff]")

#: 硬底线：无论预算多紧，最近这么多轮必须保留原文
MIN_RECENT_ROUNDS = 2


def estimate_tokens(text: str) -> int:
    """没有分词器时的估算：一个汉字约 1 个 token，其余约 4 个字符 1 个 token。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = max(0, len(text) - cjk)
    return cjk + (other + 3) // 4


def _pairs(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    pending: str | None = None
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "").strip()
        if role == "user":
            pending = content
        elif role == "assistant" and pending is not None:
            pairs.append((pending, content))
            pending = None
    if pending:
        pairs.append((pending, ""))
    return pairs


def _limits() -> tuple[int, int]:
    """(保留原文的轮数, 单条摘要的字符上限)。

    热开关优先（管理端可调，下一个任务生效），读不到回落配置——会话记忆不该因
    设置层故障而中断。
    """
    try:
        from ..core import runtime_settings

        return (
            max(0, int(runtime_settings.effective("history_recent_rounds"))),
            max(50, int(runtime_settings.effective("history_round_chars"))),
        )
    except Exception:  # noqa: BLE001 - 设置读失败回落代码缺省
        from ..core.config import settings

        return (
            max(0, int(settings.history_recent_rounds)),
            max(50, int(settings.history_round_chars)),
        )


def compress_rounds(rounds: list[tuple[str, str]], *, max_chars: int | None = None) -> str:
    """（保留但不再用于拼上下文）旧版切片压缩，仅供回退与外部调用兼容。"""
    cap = _limits()[1] if max_chars is None else max(10, int(max_chars))
    lines = []
    for question, answer in rounds:
        q = question.replace("\n", " ")[:cap]
        a = answer.replace("\n", " ")[:cap]
        lines.append(f"问：{q} 答：{a or '（没有留下回答）'}")
    return "\n".join(lines)


def _render_recent(indexed: list[tuple[int, tuple[str, str]]]) -> str:
    return "\n\n".join(
        f"用户：{q}\n助手：{a or '（没有留下回答）'}" for _, (q, a) in indexed
    )


def _pending_questions(indexed: list[tuple[int, tuple[str, str]]]) -> list[str]:
    """上一轮助手最后抛给用户的问题（下一轮很可能就是在回答它）。"""
    if not indexed:
        return []
    _, (_, answer) = indexed[-1]
    return extract_open_questions(answer)


def prepare_turn(
    history: list[dict[str, Any]],
    current: str,
    *,
    recent_rounds: int | None = None,
    round_chars: int | None = None,
    budget_chars: int | None = None,
    summaries: list[str] | None = None,
) -> tuple[str, dict[str, str]]:
    """拼出本轮任务文本，并返回分栏原文（供 context_usage 展示与排障）。

    v2.4.2：`round_chars` 语义从"每轮切多少字"改为"单条摘要字符上限"；
    新增 `budget_chars`（历史总预算，0/None = 不限），超预算按降级链丢最老整轮；
    `summaries` 是**已落库**的摘要渲染文本（按轮次升序）——命中则直接复用，
    未命中的轮次现算规则摘要（保证"刚超出窗口的那一轮"也有摘要）。
    """
    cfg_rounds, cfg_chars = _limits()
    keep = cfg_rounds if recent_rounds is None else max(0, int(recent_rounds))
    keep = max(MIN_RECENT_ROUNDS, keep)  # 硬底线
    summary_cap = cfg_chars if round_chars is None else max(50, int(round_chars))

    indexed = list(enumerate(_pairs(history), 1))
    older = indexed[:-keep] if len(indexed) > keep else []
    recent = indexed[-keep:] if keep else indexed

    cached = list(summaries or [])
    summary_blocks: list[str] = []
    for turn_no, (question, answer) in older:
        if 0 < turn_no <= len(cached) and cached[turn_no - 1].strip():
            summary_blocks.append(cached[turn_no - 1].strip())
            continue
        block = render_summary(summarize_round(turn_no, question, answer), max_chars=summary_cap)
        if block:
            summary_blocks.append(block)

    # 降级链第一步：直接生成近 8 轮原文；超预算 → 从最老整轮开始丢（丢的即时摘要）
    if budget_chars and budget_chars > 0:
        while len(recent) > MIN_RECENT_ROUNDS:
            if estimate_tokens(_render_recent(recent)) <= budget_chars:
                break
            turn_no, (question, answer) = recent.pop(0)
            block = render_summary(
                summarize_round(turn_no, question, answer), max_chars=summary_cap
            )
            if block:
                summary_blocks.append(block)

    parts: dict[str, str] = {}
    blocks: list[str] = []
    if summary_blocks:
        parts["summary"] = "\n".join(summary_blocks)
        blocks.append("【历史摘要】以下是更早轮次的结构化要点，不是原文。\n" + parts["summary"])
    if recent:
        parts["recent"] = _render_recent(recent)
        blocks.append("【近期对话】最近几轮原文（未被截断）。\n" + parts["recent"])

    # 指代对齐：上一轮问过什么，直接告诉模型——不靠代词词表（无法穷举「继续/你看着办」）
    pending = _pending_questions(recent)
    if pending:
        coref = (
            "上一轮你问过："
            + "；".join(f"『{q}』" for q in pending)
            + "。用户这句话很可能就是在回答它，按此理解直接执行，不要反问。"
        )
        parts["coref"] = coref
        blocks.append("【待确认】" + coref)
    elif any(word in current for word in _PRONOUNS) and recent:
        coref = "用户这句话里的指代，请根据上面的近期对话原文确定；对不上就说明不确定，不要猜。"
        parts["coref"] = coref
        blocks.append("【指代】" + coref)

    parts["current"] = current.strip()
    blocks.append("【本轮问题】\n" + parts["current"])
    return "\n\n".join(blocks), parts


_PROFILE_ORDER = (
    ("work", "工作背景"),
    ("personal", "个人背景"),
    ("focus", "当前关注"),
    ("history", "近期记录"),
)


def user_memory_block(
    mems: list[dict[str, Any]],
    *,
    profile: dict[str, str] | None = None,
    max_chars: int = 4000,
) -> str:
    """把背景四段和短条目拼成注入块。没有内容时返回空串。超长如实截断。"""
    chunks: list[str] = []
    for key, label in _PROFILE_ORDER:
        text = str((profile or {}).get(key) or "").strip()
        if text:
            chunks.append(f"【{label}】\n{text}")
    lines = [f"- {m.get('content', '')}" for m in mems if str(m.get("content") or "").strip()]
    if lines:
        chunks.append("【记下的条目】\n" + "\n".join(lines))
    if not chunks:
        return ""
    raw = "\n\n".join(chunks)
    body = raw[:max_chars]
    if len(raw) > max_chars:
        body += "…（长期记忆过多，已截断）"
    return (
        "【用户长期记忆】以下是用户自己写下或明确要求记住的信息，回答时可参考"
        "（不是本次对话的内容）：\n" + body
    )


def context_items(
    parts: dict[str, str],
    *,
    system: str = "",
    rules: str = "",
    tools: str = "",
) -> list[dict[str, Any]]:
    rows = [
        ("system", "系统提示", system, "#8b949e"),
        ("tools", "工具说明", tools, "#a371f7"),
        ("rules", "规则", rules, "#3fb950"),
        ("summary", "历史摘要", parts.get("summary", ""), "#f0883e"),
        ("recent", "近期对话", parts.get("recent", ""), "#79c0ff"),
        ("current", "本轮问题", parts.get("current", ""), "#f85149"),
    ]
    if parts.get("coref"):
        rows.append(("coref", "指代说明", parts["coref"], "#d2a8ff"))
    if parts.get("memory"):
        rows.append(("memory", "长期记忆", parts["memory"], "#e3b341"))
    return [
        {"key": key, "label": label, "tokens": estimate_tokens(text), "color": color}
        for key, label, text, color in rows
        if text
    ]
