"""混合意图决策：必要时改写指代，规则拿不准时调用决策小模型。

纪律：
- 独立句不改写；改写只看近期对话，不看长期记忆。
- 小模型只能从封闭标签里选，输出非法就回落规则。
- 决策失败优先单 Agent，避免一次误拆带来多段重复调用。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from .config import settings
from .llm import LlmError, LlmResult, chat as default_chat
from .planner import Plan, plan
from .token_budget import TaskTokenBudget, TokenLimitReached

logger = logging.getLogger(__name__)

ALLOWED_INTENTS = {
    "analysis",
    "cleaning",
    "report",
    "rag",
    "visualization",
    "image_restore",
    "general",
}
_PRONOUN_RE = re.compile(
    r"(这个|那个|它|刚才|上面|上述|前面|这份|该表|该报表|按这个|照这个|继续|"
    r"再来一份|再出一份|换成|改成|呢[？?]?$)"
)
_ANSWER_MARKERS = ("无法回答", "根据现有资料", "根据公司规定", "抱歉", "答案是")
_NEGATIONS = ("不要", "别", "无需", "不用", "不需要")


@dataclass
class IntentResolution:
    plan: Plan
    original_text: str
    route_text: str
    rewritten: bool = False
    rewrite_failed: bool = False
    source: str = "rule"
    recommended_mode: str | None = None
    reason: str = ""
    confidence: float | None = None
    tokens_used: int = 0


ChatFn = Callable[..., LlmResult]


def needs_context_rewrite(text: str, recent: str) -> bool:
    """有近期对话且本句离开上文不完整时才改写。"""
    current = (text or "").strip()
    if not current or not (recent or "").strip():
        return False
    normalized = re.sub(r"\s+", "", current).rstrip("。！!？?")
    return len(normalized) < 6 or bool(_PRONOUN_RE.search(current))


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError):
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError):
        return None


def _sanitize_rewrite(rewritten: str, original: str) -> str | None:
    text = (rewritten or "").strip()
    if not text:
        return None
    if len(text) > max(len(original) * 4, len(original) + 40):
        return None
    if any(marker in text for marker in _ANSWER_MARKERS):
        return None
    if ("\n" in text and len(text.splitlines()) > 3) or (
        ("。" in text or "！" in text or "!" in text) and not text.endswith(("？", "?"))
    ):
        return None
    return text


def _call(
    chat_fn: ChatFn,
    system: str,
    user: str,
    *,
    token_budget: TaskTokenBudget | None = None,
) -> LlmResult:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    reservation = token_budget.reserve_call(messages, desired_output_tokens=512) if token_budget else None
    try:
        kwargs: dict[str, Any] = {"timeout": settings.llm_timeout, "temperature": 0.0}
        if reservation is not None:
            kwargs["max_tokens"] = reservation.max_output_tokens
        result = chat_fn(settings.decision_model, messages, **kwargs)
    except Exception:
        if reservation is not None:
            reservation.cancel()
        raise
    if reservation is not None:
        reservation.complete(result.total_tokens)
    return result


def rewrite_with_context(
    original: str,
    recent: str,
    *,
    chat_fn: ChatFn = default_chat,
    token_budget: TaskTokenBudget | None = None,
) -> tuple[str, int, bool]:
    """返回（用于路由的句子, token, 是否失败）。"""
    system = (
        "你只负责把依赖上文的追问改成一句可独立理解的问题，绝对不要回答。"
        "只输出改写后的问题本身；原句已经独立就原样返回。"
        "只根据近期对话补全对象、时间和动作，不引入长期偏好或新事实。"
    )
    try:
        result = _call(
            chat_fn,
            system,
            f"【近期对话】\n{recent[-6000:]}\n\n【本轮原文】\n{original}",
            token_budget=token_budget,
        )
    except (LlmError, TokenLimitReached) as exc:
        logger.warning("指代改写失败，回落原文 | %s", exc)
        return original, 0, True
    rewritten = _sanitize_rewrite(result.content, original)
    if rewritten is None:
        logger.warning("指代改写输出不合格，回落原文 | original=%r output=%r", original, result.content[:120])
        return original, result.total_tokens, True
    return rewritten, result.total_tokens, False


def is_ambiguous(p: Plan, *, rewritten: bool = False) -> bool:
    low, high = settings.intent_ambiguity_low, settings.intent_ambiguity_high
    return (
        rewritten
        or len(p.intents) != 1
        or low <= p.score <= high
        or any(word in p.text for word in _NEGATIONS)
    )


def classify_with_model(
    text: str,
    p: Plan,
    *,
    chat_fn: ChatFn = default_chat,
    token_budget: TaskTokenBudget | None = None,
) -> tuple[list[str], str, str, float | None, int] | None:
    labels = "analysis, cleaning, report, rag, visualization, image_restore, general"
    system = (
        "你是办公助手的路由器，不回答用户问题。"
        f"意图只能从 [{labels}] 中选择，最多3个。"
        "mode只能是single或multi。只有任务存在真实的跨能力交接、一个Agent无法顺序完成时才选multi；"
        "分析后导出、画图、写文档通常是single。"
        '只输出JSON：{"intents":["analysis"],"mode":"single","reason":"一句话","confidence":0.0}'
    )
    user = (
        f"用户问题：{text}\n"
        f"规则初判：intents={p.intents or ['general']}，score={p.score}，signals={json.dumps(p.signals, ensure_ascii=False)}"
    )
    try:
        result = _call(chat_fn, system, user, token_budget=token_budget)
    except (LlmError, TokenLimitReached) as exc:
        logger.warning("决策模型不可用，回落规则 | %s", exc)
        return None
    data = _extract_json(result.content)
    if not data:
        logger.warning("决策模型未返回合法 JSON，回落规则 | output=%r", result.content[:160])
        return None
    raw_intents = data.get("intents")
    if not isinstance(raw_intents, list):
        return None
    intents = [str(item) for item in raw_intents if str(item) in ALLOWED_INTENTS]
    intents = list(dict.fromkeys(intents))[:3]
    if "general" in intents and len(intents) > 1:
        intents = [item for item in intents if item != "general"]
    mode = str(data.get("mode") or "")
    if not intents or mode not in {"single", "multi"}:
        return None
    reason = str(data.get("reason") or "").strip()[:160]
    try:
        confidence = float(data.get("confidence"))
        confidence = min(1.0, max(0.0, confidence))
    except (TypeError, ValueError):
        confidence = None
    return intents, mode, reason, confidence, result.total_tokens


def resolve_intent(
    original: str,
    recent: str = "",
    *,
    chat_fn: ChatFn = default_chat,
    token_budget: TaskTokenBudget | None = None,
) -> IntentResolution:
    route_text = original
    rewritten = False
    rewrite_failed = False
    tokens = 0
    if needs_context_rewrite(original, recent):
        route_text, used, rewrite_failed = rewrite_with_context(
            original, recent, chat_fn=chat_fn, token_budget=token_budget
        )
        tokens += used
        rewritten = route_text != original

    p = plan(route_text)
    resolution = IntentResolution(
        plan=p,
        original_text=original,
        route_text=route_text,
        rewritten=rewritten,
        rewrite_failed=rewrite_failed,
        tokens_used=tokens,
    )
    if not is_ambiguous(p, rewritten=rewritten):
        return resolution

    model = classify_with_model(route_text, p, chat_fn=chat_fn, token_budget=token_budget)
    if model is None:
        resolution.reason = "决策模型不可用或输出无效，回落规则"
        return resolution
    intents, mode, reason, confidence, used = model
    resolution.tokens_used += used
    resolution.source = "decision_model"
    resolution.recommended_mode = mode
    resolution.reason = reason
    resolution.confidence = confidence
    rule_intents = p.intents or ["general"]
    if rule_intents != intents:
        logger.warning(
            "意图规则与决策模型不一致 | text=%r rule=%s model=%s mode=%s reason=%s",
            route_text[:300],
            rule_intents,
            intents,
            mode,
            reason,
        )
    # general 是路由兜底，不放进 DAG 意图。
    p.intents = [] if intents == ["general"] else intents
    p.intent_hits = {intent: 1 for intent in p.intents}
    p.entities["decision_mode"] = mode
    p.entities["decision_reason"] = reason
    p.entities["decision_confidence"] = confidence
    return resolution
