"""LLM 调用记录仓（v2.4.3）：一行 = 一次模型调用。

为什么：2.4.2 的「需要」事故，靠翻日志的 `raw=` 才定位到"模型以为 group_by 只能单列"。
有了这张表，同类问题在管理端 5 分钟可定位：模型收到了什么、返回了什么、用了多久。

原则：
  · 落库失败**静默忽略**——可观测不能影响任务；
  · messages 里手机号脱敏（占位 138****1234）；
  · 单行几百 KB（含 5 万字观察），30 天以上由运维清理。
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")


def mask_phones(obj: Any) -> Any:
    """递归脱敏手机号 → 138****1234。"""
    if isinstance(obj, str):
        return _PHONE_RE.sub(r"\1****\2", obj)
    if isinstance(obj, dict):
        return {k: mask_phones(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_phones(x) for x in obj]
    return obj


def mask_phones_str(text: str) -> str:
    return _PHONE_RE.sub(r"\1****\2", text)


class LlmCallRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def record(
        self,
        run_id: str,
        *,
        agent: str | None,
        step: int | None,
        model: str | None,
        messages: list[dict[str, Any]],
        response_text: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        ms: int,
    ) -> None:
        """落一行调用记录；失败静默（logger 由调用方决定，这里只保证不抛）。"""
        try:
            masked = mask_phones(messages)
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO llm_call "
                        "(run_id, agent, step, model, messages_json, response_text, "
                        "prompt_tokens, completion_tokens, ms) "
                        "VALUES (:r, :a, :st, :m, :msgs, :resp, :pt, :ct, :ms)"
                    ),
                    {
                        "r": run_id[:64],
                        "a": (agent or "")[:64] or None,
                        "st": step,
                        "m": (model or "")[:128] or None,
                        "msgs": json.dumps(masked, ensure_ascii=False),
                        "resp": mask_phones_str(response_text or "")[:200000],
                        "pt": prompt_tokens,
                        "ct": completion_tokens,
                        "ms": int(ms),
                    },
                )
        except Exception:  # noqa: BLE001 - 可观测失败不阻断任务
            pass

    def list_for(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """某次任务的全部调用（不含 messages 正文，按需再取单条）。"""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT id, agent, step, model, prompt_tokens, completion_tokens, ms, created_at "
                        "FROM llm_call WHERE run_id = :r ORDER BY id LIMIT :l"
                    ),
                    {"r": run_id[:64], "l": limit},
                ).mappings().all()
        except Exception:  # noqa: BLE001
            return []
        return [dict(r) for r in rows]

    def get(self, run_id: str, call_id: int) -> dict[str, Any] | None:
        """单条调用详情（含脱敏后的 messages 与原始输出）。"""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT id, agent, step, model, messages_json, response_text, "
                        "prompt_tokens, completion_tokens, ms, created_at "
                        "FROM llm_call WHERE run_id = :r AND id = :c"
                    ),
                    {"r": run_id[:64], "c": call_id},
                ).mappings().first()
        except Exception:  # noqa: BLE001
            return None
        if not row:
            return None
        out = dict(row)
        try:
            out["messages"] = json.loads(out.pop("messages_json"))
        except (ValueError, TypeError):
            out["messages"] = []
        return out
