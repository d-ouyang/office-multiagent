"""会话/消息持久化（p6.2c）——session / message / task 表，参数化 SQL 跨 MySQL/SQLite。

一轮问答 = 一条 user message + 一条 assistant message + 一条 task 记录（run_id/用量）。
历史消息只存终答正文（中间事件流不落库——那是过程不是结论；thinking/步骤实时看即可）。
"""
from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .db import get_engine


def new_session_id() -> str:
    return f"s-{secrets.token_hex(8)}"


class SessionRepo:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or get_engine()

    def create_session(self, user_id: int, model: str | None = None) -> str:
        sid = new_session_id()
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO session (id, user_id, model) VALUES (:i, :u, :m)"),
                {"i": sid, "u": user_id, "m": model},
            )
        return sid

    def update_session_model(self, session_id: str, model: str | None) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE session SET model = :m WHERE id = :i"),
                {"i": session_id, "m": model},
            )

    def get_session_model(self, session_id: str) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT model FROM session WHERE id = :i"), {"i": session_id}
            ).first()
        return row[0] if row else None

    def session_belongs_to(self, session_id: str, user_id: int) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM session WHERE id = :i AND user_id = :u"),
                {"i": session_id, "u": user_id},
            ).first()
        return row is not None

    def list_sessions(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """会话列表：title 取首条 user 消息前 20 字（无消息则"新会话"）。

        p6.12：updated_at = 最后一条消息时间（无消息回落 session.created_at），
        按 updated_at 倒序——侧栏时间显示"最后一次问答时间"，不再全是加载时刻。
        """
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT s.id AS session_id, "
                    "  (SELECT SUBSTRING(content, 1, 20) FROM message m "
                    "   WHERE m.session_id = s.id AND m.role = 'user' ORDER BY m.id LIMIT 1) AS title, "
                    "  s.created_at AS created_at, "
                    "  COALESCE((SELECT MAX(m2.created_at) FROM message m2 "
                    "     WHERE m2.session_id = s.id), s.created_at) AS updated_at "
                    "FROM session s WHERE s.user_id = :u "
                    "ORDER BY updated_at DESC LIMIT :l"
                ),
                {"u": user_id, "l": limit},
            ).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            d["title"] = (d.get("title") or "新会话").strip() or "新会话"
            d["created_at"] = str(d.get("created_at") or "")
            d["updated_at"] = str(d.get("updated_at") or "")
            out.append(d)
        return out

    def append_message(self, session_id: str, role: str, content: str, trace: str | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO message (session_id, role, content, trace) VALUES (:s, :r, :c, :t)"),
                {"s": session_id, "r": role, "c": content, "t": trace},
            )

    def list_messages(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT role, content, trace, created_at FROM message "
                    "WHERE session_id = :s ORDER BY id LIMIT :l"
                ),
                {"s": session_id, "l": limit},
            ).mappings().all()
        return [
            {
                "role": r["role"],
                "content": r["content"],
                "trace": r["trace"],  # p6.7：过程事件 JSON（assistant 消息有；user 消息为 None）
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ]

    def record_task(
        self,
        task_id: str,
        session_id: str,
        task_text: str,
        result: str,
        tokens_used: int,
        status: str,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO task (id, session_id, complexity, status, text, result, tokens_used) "
                    "VALUES (:i, :s, NULL, :st, :t, :r, :tk)"
                ),
                {"i": task_id, "s": session_id, "st": status, "t": task_text, "r": result, "tk": int(tokens_used)},
            )
