"""会话轮次的结构化摘要（v2.4.2）。

为什么存在：旧实现用 `answer[:80]` 切片当"摘要"，把 730 字的回答砍成
"- 时…"这种断句，结尾的「需要我导出成文档吗」直接丢失——用户回「需要」时
模型无从对上。摘要必须**保留结论、数字、产物与未决问题**，而不是留前 N 个字。

为什么先做规则版而不是 LLM 版：
  · 纯函数，零延迟、零成本、可单测、结果确定（同一输入永远同一输出）；
  · LLM 摘要要多一次模型调用，且失败时还得回落——先把"不丢关键信息"这件事做对，
    换用 LLM 只是把抽取质量再抬一档，接口不变（`summarize_round` → `render_summary`）。

抽取的四类信息，对应"下一轮最可能用到什么"：
  · conclusions —— 做了什么、得出什么（下一轮可能追问细节）
  · numbers     —— 出现过的关键数字（下一轮可能引用或对比）
  · artifacts   —— 产出的文件（下一轮可能要求导出/修改）
  · open_questions —— 助手最后问的问题（**下一轮很可能就是在回答它**）
"""
from __future__ import annotations

import re
from typing import Any

#: 句子切分：中文句号/问号/叹号/分号/换行
_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;])|\n+")
#: 结论线索词——带这些词的句子优先当结论
_CONCLUSION_HINTS = ("结论", "要点", "总计", "合计", "最高", "最低", "环比", "同比", "建议", "注意", "总结")
#: 数字：整数/小数/百分比/金额
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|元|万元|万|亿|单|笔|个|条|组|人|天)?")
#: 文件名：必须带**已知扩展名**。此前写成 `[\w.]+\.\w+` 会把金额 "18,830.18" 当成文件名
#: （真跑见证：摘要的"产物"列里出现 830.18、136.20 这种金额）。
_FILE_RE = re.compile(
    r"([\w\u4e00-\u9fff\-（）()]{1,60}\."
    r"(?:md|markdown|docx?|pdf|xlsx?|csv|pptx?|png|jpe?g|svg|txt|json|zip))",
    re.IGNORECASE,
)
#: 问句判定
_QUESTION_TAIL = re.compile(r"[?？]\s*$")
_QUESTION_WORDS = ("吗", "呢", "要不要", "是否", "需不需要", "还是")

MAX_CONCLUSIONS = 3
MAX_NUMBERS = 8
MAX_ARTIFACTS = 5
MAX_OPEN_QUESTIONS = 2


def _sentences(text: str) -> list[str]:
    out = []
    for raw in _SENT_SPLIT.split(text or ""):
        s = (raw or "").strip().lstrip("#-* ").strip()
        if len(s) >= 6:  # 太短的碎片（"- 时"）没有信息量
            out.append(s)
    return out


def _is_question(sentence: str) -> bool:
    if _QUESTION_TAIL.search(sentence):
        return True
    tail = sentence[-6:]
    return any(w in tail for w in _QUESTION_WORDS)


def extract_open_questions(answer: str, limit: int = MAX_OPEN_QUESTIONS) -> list[str]:
    """抽出助手回答末尾的提问（下一轮大概率在回答它）。

    只看最后 10 句：中间的设问多是修辞（"为什么要这样？因为…"），末尾的才是抛给用户的。
    取最后 limit 个，调用方按"最后一个才是真正待回答的"使用。
    """
    sents = _sentences(answer)[-10:]
    found = [s for s in sents if _is_question(s)]
    return found[-limit:]


def _conclusions(answer: str, limit: int = MAX_CONCLUSIONS) -> list[str]:
    """优先取带结论词/数字的句子，其次取靠前的实质句。"""
    sents = [s for s in _sentences(answer) if not _is_question(s)]
    scored: list[tuple[int, str]] = []
    for idx, s in enumerate(sents):
        score = 0
        if any(h in s for h in _CONCLUSION_HINTS):
            score += 2
        if _NUMBER_RE.search(s):
            score += 1
        if score:
            scored.append((score, s))
    picked = [s for _, s in sorted(scored, key=lambda x: -x[0])][:limit]
    if picked:
        return picked
    return sents[:limit]


def _numbers(text: str, limit: int = MAX_NUMBERS) -> list[str]:
    seen: list[str] = []
    for m in _NUMBER_RE.findall(text or ""):
        val = m.strip()
        if len(val) >= 2 and val not in seen:
            seen.append(val)
        if len(seen) >= limit:
            break
    return seen


def _artifacts(answer: str, limit: int = MAX_ARTIFACTS) -> list[str]:
    found: list[str] = []
    for m in _FILE_RE.findall(answer or ""):
        if m not in found:
            found.append(m)
        if len(found) >= limit:
            break
    return found


def summarize_round(turn_no: int, question: str, answer: str) -> dict[str, Any]:
    """一轮 → 结构化摘要。字段名与 `session_summary.payload` 一致。

    注意 intent 不走句子切分：用户的短问题（「需要」「继续」只有两三个字）会被
    长度过滤掉，而它恰恰是最该保留的上下文线索。
    """
    intent = (question or "").strip().replace("\n", " ")[:120]
    return {
        "turn": int(turn_no),
        "user_intent": intent,
        "conclusions": _conclusions(answer),
        "numbers": _numbers(answer),
        "artifacts": _artifacts(answer),
        "open_questions": extract_open_questions(answer),
    }


_SUMMARY_SYSTEM = """你是会话摘要器。把一轮对话压成 JSON，只输出 JSON，不要任何解释。

必须遵守：
1. numbers 里的数字必须从原文**原样复制**（含千分位与单位），禁止改写、取整或估算；
2. conclusions 只写原文明确给出的结论，最多 3 条，每条不超过 60 字；
3. artifacts 只写原文出现过的文件名；
4. open_questions 抄原文最后抛给用户的问题（这一条最重要，下一轮要靠它对齐指代）；
5. 原文没有的内容留空数组，不要编。

输出格式：
{"user_intent": "用户这一轮想做什么（一句话）", "conclusions": ["..."], "numbers": ["..."], "artifacts": ["..."], "open_questions": ["..."]}"""


def summarize_with_llm(
    turn_no: int,
    question: str,
    answer: str,
    *,
    model_id: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """调小模型做归纳；任何失败都返回 None（调用方回落规则摘要，绝不阻断任务）。

    为什么还要配规则兜底：模型改写数字是本场景最危险的失真——摘要是下一轮唯一的事实
    来源，写错一个数字，后面几轮全错且无人察觉。所以数字/产物/问句以规则抽取为准，
    模型只负责"用一句话说清这轮在做什么、得出什么结论"。
    """
    from ..core.config import settings
    from ..core.llm import chat
    from .brain import extract_json  # 复用四层容错解析（尾逗号/裸换行/代码块）

    mid = model_id or str(getattr(settings, "llm_brain_model", "") or "")
    if not mid:
        return None
    payload = f"【用户】\n{(question or '')[:2000]}\n\n【助手】\n{(answer or '')[:6000]}"
    try:
        res = chat(
            mid,
            [
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": payload},
            ],
            timeout=timeout,
            temperature=0.1,
            max_tokens=600,
        )
    except Exception:  # noqa: BLE001 - 摘要失败不能影响任务
        return None
    data = extract_json(getattr(res, "content", "") or "")
    if not isinstance(data, dict):
        return None

    def _strs(key: str, cap: int, limit: int) -> list[str]:
        raw = data.get(key) or []
        if not isinstance(raw, list):
            return []
        return [str(x)[:cap] for x in raw][:limit]

    return {
        "turn": int(turn_no),
        "user_intent": str(data.get("user_intent") or "")[:120],
        "conclusions": _strs("conclusions", 120, MAX_CONCLUSIONS),
        "numbers": _strs("numbers", 24, MAX_NUMBERS),
        "artifacts": _strs("artifacts", 80, MAX_ARTIFACTS),
        "open_questions": _strs("open_questions", 120, MAX_OPEN_QUESTIONS),
    }


def merge_summaries(rule: dict[str, Any], llm: dict[str, Any] | None) -> dict[str, Any]:
    """合并：叙述层（意图/结论）用模型，事实层（数字/产物/问句）用规则。"""
    if not llm:
        return rule
    return {
        "turn": rule["turn"],
        "user_intent": llm.get("user_intent") or rule["user_intent"],
        "conclusions": llm.get("conclusions") or rule["conclusions"],
        "numbers": rule["numbers"] or llm.get("numbers") or [],
        "artifacts": rule["artifacts"] or llm.get("artifacts") or [],
        # 问句以规则为准：模型容易把它"总结掉"，而它正是下一轮指代对齐的关键
        "open_questions": rule["open_questions"] or llm.get("open_questions") or [],
    }


def summarize_turn(
    turn_no: int,
    question: str,
    answer: str,
    *,
    use_llm: bool = True,
    model_id: str | None = None,
) -> dict[str, Any]:
    """一轮的最终摘要：规则抽取打底，可选叠加模型归纳。"""
    rule = summarize_round(turn_no, question, answer)
    if not use_llm:
        return rule
    return merge_summaries(rule, summarize_with_llm(turn_no, question, answer, model_id=model_id))


def render_summary(payload: dict[str, Any], *, max_chars: int = 400) -> str:
    """把结构化摘要渲染成一段紧凑文本（约 150~300 字）。"""
    turn = payload.get("turn")
    intent = str(payload.get("user_intent") or "").strip()
    parts: list[str] = []
    if turn:
        parts.append(f"[第{turn}轮] {intent}")
    elif intent:
        parts.append(intent)

    conclusions = [str(x) for x in (payload.get("conclusions") or [])]
    if conclusions:
        parts.append("结论：" + "；".join(conclusions))

    numbers = [str(x) for x in (payload.get("numbers") or [])]
    if numbers:
        parts.append("数字：" + "、".join(numbers))

    artifacts = [str(x) for x in (payload.get("artifacts") or [])]
    if artifacts:
        parts.append("产物：" + "、".join(artifacts))

    questions = [str(x) for x in (payload.get("open_questions") or [])]
    if questions:
        parts.append("待确认：" + "；".join(questions))

    text = "\n".join(parts)
    if max_chars > 0 and len(text) > max_chars:
        # 摘要本身超长时按行截（保留前面的结论/数字，弃最后的待确认除外）
        keep: list[str] = []
        used = 0
        for part in parts:
            if used + len(part) > max_chars and keep:
                break
            keep.append(part)
            used += len(part) + 1
        text = "\n".join(keep)
    return text
