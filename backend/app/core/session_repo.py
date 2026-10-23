"""会话/消息持久化（p6.2c）——session / message / task 表，参数化 SQL 跨 MySQL/SQLite。

一轮问答 = 一条 user message + 一条 assistant message + 一条 task 记录（run_id/用量）。
历史消息只存终答正文（中间事件流不落库——那是过程不是结论；thinking/步骤实时看即可）。
"""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .db import get_engine


def new_session_id() -> str:
    return f"s-{secrets.token_hex(8)}"


def _iso_utc(v: Any) -> str:
    """时间字段统一输出带 UTC 标记的 ISO（如 '2026-10-21T13:40:13.380547Z'）。

    库内统一存 UTC（MySQL/SQLite 的 CURRENT_TIMESTAMP 都是 UTC）——p6.12c 修"差 8 小时"：
    旧实现裸字符串无时区，前端 new Date() 按本地时间解析，UTC 时间被当成本地时间（差 8h）。
    带上 Z 后前端 Date 自动转本地显示；兼容 datetime（MySQL）与 str（SQLite）两种返回类型。
    """
    if isinstance(v, datetime):
        return v.isoformat(sep="T", timespec="microseconds") + "Z"
    s = str(v or "")
    if not s or s.endswith("Z"):
        return s
    return s.replace(" ", "T", 1) + "Z"


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

    def rename_session(self, session_id: str, title: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE session SET title = :t WHERE id = :i"),
                {"i": session_id, "t": title[:60]},
            )

    def set_pinned(self, session_id: str, pinned: bool) -> None:
        with self.engine.begin() as conn:
            if pinned:
                conn.execute(
                    text("UPDATE session SET pinned = 1, pinned_at = CURRENT_TIMESTAMP WHERE id = :i"),
                    {"i": session_id},
                )
            else:
                conn.execute(
                    text("UPDATE session SET pinned = 0, pinned_at = NULL WHERE id = :i"),
                    {"i": session_id},
                )

    def delete_session(self, session_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM message WHERE session_id = :i"), {"i": session_id})
            conn.execute(text("DELETE FROM task WHERE session_id = :i"), {"i": session_id})
            conn.execute(text("DELETE FROM session WHERE id = :i"), {"i": session_id})

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
                    "  COALESCE(NULLIF(TRIM(s.title), ''), "
                    "    (SELECT SUBSTRING(content, 1, 20) FROM message m "
                    "     WHERE m.session_id = s.id AND m.role = 'user' ORDER BY m.id LIMIT 1)) AS title, "
                    "  COALESCE(s.pinned, 0) AS pinned, "
                    "  s.created_at AS created_at, "
                    "  COALESCE((SELECT MAX(m2.created_at) FROM message m2 "
                    "     WHERE m2.session_id = s.id), s.created_at) AS updated_at "
                    "FROM session s WHERE s.user_id = :u "
                    "ORDER BY COALESCE(s.pinned, 0) DESC, s.pinned_at DESC, updated_at DESC LIMIT :l"
                ),
                {"u": user_id, "l": limit},
            ).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            d["title"] = (d.get("title") or "新会话").strip() or "新会话"
            d["pinned"] = bool(d.get("pinned"))
            d["created_at"] = _iso_utc(d.get("created_at"))
            d["updated_at"] = _iso_utc(d.get("updated_at"))
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
        out = [
            {
                "role": r["role"],
                "content": r["content"],
                "trace": r["trace"],
                "created_at": _iso_utc(r["created_at"]),
            }
            for r in rows
        ]
        self._attach_turn_usage(session_id, out)
        return out

    def _attach_turn_usage(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """给还没有模型信息的助手消息补上账本里的 model / tokens。

        按时间尾部对齐：最近的结算对应最近的助手消息。trace 里已有的模型优先，这里只填空。
        """
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT l.model AS model, l.settle AS settle FROM token_ledger l "
                    "JOIN session s ON s.user_id = l.user_id "
                    "WHERE s.id = :sid AND l.settle IS NOT NULL ORDER BY l.id"
                ),
                {"sid": session_id},
            ).mappings().all()
        assistants = [m for m in messages if m.get("role") == "assistant"]
        n = min(len(rows), len(assistants))
        for msg, row in zip(assistants[-n:], rows[-n:]):
            if not msg.get("model") and row.get("model"):
                msg["model"] = row["model"]
            if msg.get("tokens") is None and row.get("settle") is not None:
                msg["tokens"] = int(row["settle"])

    def trim_messages_after(self, session_id: str, keep: int) -> int:
        """保留按 id 排序的前 keep 条消息，删掉其后的。

        编辑某条用户消息并重发时，keep = 该消息在列表中的下标（它自己以及之后的回复都删掉）。
        """
        if keep < 0:
            keep = 0
        with self.engine.begin() as conn:
            rows = conn.execute(
                text("SELECT id FROM message WHERE session_id = :s ORDER BY id"),
                {"s": session_id},
            ).all()
            drop = [r[0] for r in rows[keep:]]
            if not drop:
                return 0
            params: dict[str, Any] = {"s": session_id}
            holders = []
            for i, mid in enumerate(drop):
                key = f"id{i}"
                holders.append(f":{key}")
                params[key] = mid
            res = conn.execute(
                text(
                    f"DELETE FROM message WHERE session_id = :s AND id IN ({', '.join(holders)})"
                ),
                params,
            )
            return int(res.rowcount or 0)

    def record_task(
        self,
        task_id: str,
        session_id: str,
        task_text: str,
        result: str,
        tokens_used: int,
        status: str,
        *,
        pause_reason: str | None = None,
        pause_payload: str | None = None,
        retry_of: str | None = None,
        request_json: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO task (id, session_id, complexity, status, text, result, tokens_used, "
                    "pause_reason, pause_payload, retry_of, request_json) "
                    "VALUES (:i, :s, NULL, :st, :t, :r, :tk, :pr, :pp, :ro, :rq)"
                ),
                {
                    "i": task_id,
                    "s": session_id,
                    "st": status,
                    "t": task_text,
                    "r": result,
                    "tk": int(tokens_used),
                    "pr": pause_reason,
                    "pp": pause_payload,
                    "ro": retry_of,
                    "rq": request_json,
                },
            )

    def mark_task_resumed(self, task_id: str) -> None:
        """续跑开始时把原任务标为 resumed（p7.1）——否则刷新后横幅会反复提示旧暂停。"""
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE task SET status = 'resumed' WHERE id = :i AND status LIKE 'paused%'"),
                {"i": task_id},
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """按 id 取任务（p7.1：暂停详情/续跑入口用）。"""
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, session_id, status, text, result, tokens_used, "
                    "pause_reason, pause_payload, retry_of, created_at "
                    "FROM task WHERE id = :i"
                ),
                {"i": task_id},
            ).mappings().first()
        return dict(row) if row else None

    def task_belongs_to(self, task_id: str, user_id: int) -> bool:
        """归属校验：task → session → user（防越权暂停/续跑别人的任务）。"""
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM task t JOIN session s ON s.id = t.session_id "
                    "WHERE t.id = :i AND s.user_id = :u LIMIT 1"
                ),
                {"i": task_id, "u": user_id},
            ).first()
        return row is not None

    def task_owner_id(self, task_id: str) -> int | None:
        """任务的归属用户 id（管理端代续跑用：以原 owner 身份计费）。"""
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT s.user_id FROM task t JOIN session s ON s.id = t.session_id "
                    "WHERE t.id = :i LIMIT 1"
                ),
                {"i": task_id},
            ).first()
        return int(row[0]) if row and row[0] is not None else None

    def username_of(self, user_id: int | None) -> str:
        """user_id → username（附件目录/身份展示用；取不到回落 office-service）。"""
        if user_id is None:
            return "office-service"
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT username FROM `user` WHERE id = :u"), {"u": user_id}
            ).first()
        return str(row[0]) if row else "office-service"

    def list_tasks(
        self,
        user_id: int,
        *,
        status: str | None = None,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """我的任务列表（p7.1：前端刷新后还能看到"上次暂停"的横幅并续跑）。"""
        sql = (
            "SELECT t.id, t.session_id, t.status, t.text, t.tokens_used, "
            "t.pause_reason, t.pause_payload, t.retry_of, t.created_at "
            "FROM task t JOIN session s ON s.id = t.session_id WHERE s.user_id = :u"
        )
        params: dict[str, Any] = {"u": user_id, "l": int(limit)}
        if status:
            sql += " AND t.status = :st"
            params["st"] = status
        if session_id:
            sql += " AND t.session_id = :sid"
            params["sid"] = session_id
        sql += " ORDER BY t.created_at DESC LIMIT :l"
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [dict(r) for r in rows]
