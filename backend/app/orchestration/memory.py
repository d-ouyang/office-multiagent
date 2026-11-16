"""会话记忆：最近几轮原样保留，更早的压成摘要，并提示指代。"""
from __future__ import annotations

import re
from typing import Any

RECENT_ROUNDS = 4
_PRONOUNS = ("这个", "那个", "它", "他", "她", "刚才", "上面", "上述", "这份", "该表", "该报表")
_CJK = re.compile(r"[\u4e00-\u9fff]")


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
    """v2.3.0-p1.0：保留原文的轮数 + 压缩后每段字符数。

    热开关优先（管理端可调，下一个任务生效），读不到回落配置——会话记忆不该因
    设置层故障而中断。返回 (轮数, 字符数)，轮数 0 表示全部压成摘要。
    """
    try:
        from ..core import runtime_settings

        return (
            max(0, int(runtime_settings.effective("history_recent_rounds"))),
            max(10, int(runtime_settings.effective("history_round_chars"))),
        )
    except Exception:  # noqa: BLE001 - 设置读失败回落代码缺省
        from ..core.config import settings

        return (
            max(0, int(settings.history_recent_rounds)),
            max(10, int(settings.history_round_chars)),
        )


def compress_rounds(rounds: list[tuple[str, str]], *, max_chars: int | None = None) -> str:
    """把问答对压成一行。max_chars=None 取配置值（v2.3.0-p1.0 起不再写死 80）。"""
    cap = _limits()[1] if max_chars is None else max(10, int(max_chars))
    lines = []
    for question, answer in rounds:
        q = question.replace("\n", " ")[:cap]
        a = answer.replace("\n", " ")[:cap]
        lines.append(f"问：{q} 答：{a or '（没有留下回答）'}")
    return "\n".join(lines)


def prepare_turn(
    history: list[dict[str, Any]],
    current: str,
    *,
    recent_rounds: int | None = None,
    round_chars: int | None = None,
) -> tuple[str, dict[str, str]]:
    """拼出本轮任务文本，并返回分栏原文。当前问题不要放进 history。

    v2.3.0-p1.0：轮数与每段长度改为可配（显式参数 > 运行时设置 > 配置缺省）；
    recent_rounds=0 表示全部压成摘要（注意 Python 的 `x[:-0]` 是空列表，需单独分支）。
    """
    cfg_rounds, cfg_chars = _limits()
    keep = cfg_rounds if recent_rounds is None else max(0, int(recent_rounds))
    chars = cfg_chars if round_chars is None else max(10, int(round_chars))
    rounds = _pairs(history)
    if keep <= 0:
        older, recent = rounds, []
    else:
        older, recent = rounds[:-keep], rounds[-keep:]
    parts: dict[str, str] = {}
    summary = compress_rounds(older, max_chars=chars)
    if summary:
        parts["summary"] = summary
    if recent:
        parts["recent"] = compress_rounds(recent, max_chars=chars).replace("问：", "用户：").replace(" 答：", "\n助手：")
    parts["current"] = current.strip()
    blocks = []
    if summary:
        blocks.append("【历史摘要】以下是更早对话压缩后的内容，不是原文。\n" + summary)
    if recent:
        blocks.append("【近期对话】最近几轮原文要点。\n" + parts["recent"])
    if any(word in current for word in _PRONOUNS) and (summary or recent):
        blocks.append("【指代】用户这句话里的这个、那个、它、刚才等，只根据上面的摘要和近期对话确定。对不上就说明不确定，不要猜一个没出现过的对象。")
        parts["coref"] = "指代需根据近期对话和历史摘要消解"
    blocks.append("【本轮问题】\n" + current.strip())
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
