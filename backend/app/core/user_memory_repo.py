"""显式长期记忆（p6.29，P1 拍板：user_memory 表，用户可查可删）。

设计要点（对照 48 页参考架构第 ④ 步「记忆检索」缺口）：
  · **显式**：只有用户明确要求"记住 XX"（或自己在前端添加）才写入——
    Agent 不许自行偷偷记；用户没让记就不要调 remember。
  · **可查可删**：GET /memory 列出自己的全部记忆、DELETE /memory/{id} 删除；
    记忆的权力在用户手里，不在系统手里。
  · **只增不改**：没有 update 接口——改 = 删了重加，语义清晰、留痕简单。
  · 满了如实拒绝（不静默淘汰最旧的）：淘汰会让"用户以为记住的东西"消失，
    这种静默丢失比"记忆已满"的报错糟糕得多。
  · 去重：同用户同内容不重复写（幂等），返回已有行。

注入方式：每轮把记忆摘要块拼进任务文本前部（routes._stream_task），
同时计入 context_usage 的 memory 分栏（orchestration/memory.context_items）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .config import settings
from .db import get_engine

logger = logging.getLogger(__name__)


class MemoryFull(Exception):
    """记忆条数已达上限（调用方转成友好提示，不静默淘汰）。"""


class ContentTooLong(Exception):
    """单条内容超长。"""


def _iso_utc(v: Any) -> str:
    if isinstance(v, datetime):
        return v.isoformat(sep="T", timespec="microseconds") + "Z"
    s = str(v or "")
    if not s or s.endswith("Z"):
        return s
    return s.replace(" ", "T", 1) + "Z"


class UserMemoryRepo:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or get_engine()

    def count(self, user_id: int) -> int:
        with self.engine.connect() as conn:
            return int(
                conn.execute(
                    text("SELECT COUNT(*) FROM user_memory WHERE user_id = :u"),
                    {"u": user_id},
                ).scalar()
                or 0
            )

    def add(self, user_id: int, content: str, *, source: str = "agent") -> dict[str, Any]:
        """写入一条记忆。同内容幂等；满了抛 MemoryFull、超长抛 ContentTooLong。"""
        content = (content or "").strip()
        if not content:
            raise ValueError("记忆内容不能为空")
        if len(content) > settings.user_memory_content_chars:
            raise ContentTooLong(
                f"记忆内容最多 {settings.user_memory_content_chars} 字（当前 {len(content)} 字）"
            )
        with self.engine.begin() as conn:
            dup = conn.execute(
                text(
                    "SELECT id, content, source, created_at FROM user_memory "
                    "WHERE user_id = :u AND content = :c LIMIT 1"
                ),
                {"u": user_id, "c": content},
            ).mappings().first()
            if dup:
                row = dict(dup)
                row["created_at"] = _iso_utc(row.get("created_at"))
                row["duplicated"] = True
                return row
            n = int(
                conn.execute(
                    text("SELECT COUNT(*) FROM user_memory WHERE user_id = :u"), {"u": user_id}
                ).scalar()
                or 0
            )
            if n >= settings.user_memory_max_items:
                raise MemoryFull(
                    f"记忆已满（上限 {settings.user_memory_max_items} 条），请先删除不再需要的记忆"
                )
            rid = conn.execute(
                text(
                    "INSERT INTO user_memory (user_id, content, source) VALUES (:u, :c, :s)"
                ),
                {"u": user_id, "c": content, "s": source},
            )
            memory_id = int(getattr(rid, "lastrowid", 0) or 0)
        logger.info("user_memory add user_id=%s id=%s chars=%s source=%s", user_id, memory_id, len(content), source)
        return {"id": memory_id, "content": content, "source": source, "duplicated": False}

    def list_for(self, user_id: int, *, limit: int | None = None, keyword: str = "") -> list[dict[str, Any]]:
        """列出用户记忆（新的在前）。keyword 非空时按 LIKE 过滤。"""
        sql = (
            "SELECT id, content, source, created_at FROM user_memory WHERE user_id = :u"
        )
        params: dict[str, Any] = {"u": user_id}
        if keyword:
            sql += " AND content LIKE :k"
            params["k"] = f"%{keyword}%"
        sql += " ORDER BY id DESC LIMIT :l"
        params["l"] = max(1, int(limit or settings.user_memory_max_items))
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        out = []
        for r in rows:
            row = dict(r)
            row["created_at"] = _iso_utc(row.get("created_at"))
            out.append(row)
        return out

    def delete(self, user_id: int, memory_id: int) -> bool:
        """删除自己的记忆；不属于该用户（或不存在）返回 False——越权与 404 同形，不泄露存在性。"""
        with self.engine.begin() as conn:
            res = conn.execute(
                text("DELETE FROM user_memory WHERE id = :i AND user_id = :u"),
                {"i": memory_id, "u": user_id},
            )
            return bool(getattr(res, "rowcount", 0))
