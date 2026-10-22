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


def compress_rounds(rounds: list[tuple[str, str]]) -> str:
    lines = []
    for question, answer in rounds:
        q = question.replace("\n", " ")[:80]
        a = answer.replace("\n", " ")[:80]
        lines.append(f"问：{q} 答：{a or '（没有留下回答）'}")
    return "\n".join(lines)


def prepare_turn(history: list[dict[str, Any]], current: str) -> tuple[str, dict[str, str]]:
    """拼出本轮任务文本，并返回分栏原文。当前问题不要放进 history。"""
    rounds = _pairs(history)
    older, recent = rounds[:-RECENT_ROUNDS], rounds[-RECENT_ROUNDS:]
    parts: dict[str, str] = {}
    summary = compress_rounds(older)
    if summary:
        parts["summary"] = summary
    if recent:
        parts["recent"] = compress_rounds(recent).replace("问：", "用户：").replace(" 答：", "\n助手：")
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
    return [
        {"key": key, "label": label, "tokens": estimate_tokens(text), "color": color}
        for key, label, text, color in rows
        if text
    ]
