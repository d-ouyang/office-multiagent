"""会话摘要仓（v2.4.2）：一轮一条结构化摘要的读写。

设计要点：
  · `turn_no` 与 QA 对顺序对齐（第 N 个问答对 = turn_no N）；
  · 生成后**永久复用**，不因后续轮次重算（只有摘要总量超预算才合并最老几条）；
  · `engine` 记录来源（rule / llm），便于排查"这条摘要是谁生成的"；
  · 所有读写失败都返回空/静默，摘要能力不能阻断任务。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine


class SessionSummaryRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert(
        self,
        session_id: str,
        turn_no: int,
        payload: dict[str, Any],
        rendered: str,
        *,
        engine_name: str = "rule",
    ) -> None:
        """写入/更新某轮摘要（同轮重复调用时覆盖，幂等）。"""
        stmt = text(
            "INSERT INTO session_summary (session_id, turn_no, payload, rendered, engine) "
            "VALUES (:s, :t, :p, :r, :e) "
            "ON DUPLICATE KEY UPDATE payload=VALUES(payload), rendered=VALUES(rendered), "
            "engine=VALUES(engine)"
        )
        with self.engine.begin() as conn:
            conn.execute(
                stmt,
                {
                    "s": session_id,
                    "t": int(turn_no),
                    "p": json.dumps(payload, ensure_ascii=False),
                    "r": rendered,
                    "e": engine_name[:16],
                },
            )

    def list_rendered(self, session_id: str) -> list[str]:
        """按轮次升序返回已渲染摘要；没有表/查询失败时返回空列表。"""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT rendered FROM session_summary WHERE session_id=:s ORDER BY turn_no"
                    ),
                    {"s": session_id},
                ).all()
        except Exception:  # noqa: BLE001 - 未迁移/库异常都不该阻断任务
            return []
        return [str(r[0]) for r in rows if r and r[0]]

    def list_payloads(self, session_id: str) -> list[dict[str, Any]]:
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT payload FROM session_summary WHERE session_id=:s ORDER BY turn_no"
                    ),
                    {"s": session_id},
                ).all()
        except Exception:  # noqa: BLE001
            return []
        out: list[dict[str, Any]] = []
        for (raw,) in rows:
            if not raw:
                continue
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict):
                out.append(data)
        return out

    def last_open_questions(self, session_id: str, limit: int = 2) -> list[str]:
        """最近一条摘要里的未决问题（跨会话轮次兜底用）。"""
        payloads = self.list_payloads(session_id)
        if not payloads:
            return []
        questions = payloads[-1].get("open_questions") or []
        return [str(q) for q in questions][-limit:]
