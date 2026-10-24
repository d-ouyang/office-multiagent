"""Token 池两段式扣减（p4.2）——设计文档 §十四：reserve 预扣 + settle 结算，原子防并行超额。

- reserve：原子 `UPDATE wallet SET balance=balance-:a WHERE user_id=:u AND balance>=:a`，
  影响行数 0 即余额不足 → 拒绝（防并行子 Agent 超额，§十四）。
- settle：按实际用量补差 `reserved - actual`（可正可负），落 `token_ledger`。
- 引擎可注入：生产 MySQL、测试 SQLite 内存——同一条参数化原子 SQL 两边都成立。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .session_repo import _iso_utc


@dataclass
class ReserveResult:
    ok: bool
    balance: int | None = None
    detail: str | None = None


class TokenPool:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def balance(self, user_id: int) -> int:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT balance FROM wallet WHERE user_id=:u"), {"u": user_id}
            ).first()
            return int(row[0]) if row else 0

    def recent(self, user_id: int, limit: int = 10) -> list[dict]:
        """最近流水（p6.4 /quota 展示用；p7.1 带 kind/note；p6.26 充值带 amount）。"""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, task_id, model, reserve, settle, kind, note, amount, created_at "
                    "FROM token_ledger WHERE user_id=:u ORDER BY id DESC LIMIT :l"
                ),
                {"u": user_id, "l": limit},
            ).mappings().all()
        return [
            {
                "task_id": r["task_id"],
                "model": r["model"],
                "reserve": r["reserve"],
                "settle": r["settle"],
                "kind": r.get("kind") or "task",
                "note": r.get("note"),
                "amount": r.get("amount"),
                "created_at": _iso_utc(r["created_at"]),
            }
            for r in rows
        ]

    def credit(
        self,
        user_id: int,
        amount: int,
        *,
        note: str | None = None,
        operator_id: int | None = None,
    ) -> int:
        """充值（p7.1，管理端）：余额 +amount，账本记一条 kind=recharge。

        - amount 必须 > 0（0/负数直接拒，防误操作把余额冲成负数）；
        - 钱包不存在则建一条（新用户首次充值不必先建钱包）；
        - 返回最新余额。
        """
        if amount <= 0:
            raise ValueError("充值数量必须大于 0")
        label = note or ""
        if operator_id is not None:
            label = f"{label}（操作人 {operator_id}）" if label else f"操作人 {operator_id}"
        with self.engine.begin() as conn:
            updated = conn.execute(
                text("UPDATE wallet SET balance = balance + :a WHERE user_id=:u"),
                {"a": amount, "u": user_id},
            )
            if updated.rowcount == 0:
                conn.execute(
                    text("INSERT INTO wallet (user_id, balance) VALUES (:u, :a)"),
                    {"u": user_id, "a": amount},
                )
            conn.execute(
                text(
                    "INSERT INTO token_ledger (user_id, task_id, model, reserve, settle, kind, note, amount) "
                    "VALUES (:u, NULL, NULL, NULL, NULL, 'recharge', :n, :a)"
                ),
                {"u": user_id, "n": label[:255] or None, "a": amount},
            )
            row = conn.execute(
                text("SELECT balance FROM wallet WHERE user_id=:u"), {"u": user_id}
            ).first()
            return int(row[0]) if row else amount

    def reserve(
        self,
        user_id: int,
        amount: int,
        *,
        task_id: str | None = None,
        model: str | None = None,
    ) -> ReserveResult:
        """预扣；余额不足返回 ok=False（原子，防超额）。"""
        if amount <= 0:
            return ReserveResult(ok=True, balance=self.balance(user_id))
        with self.engine.begin() as conn:
            res = conn.execute(
                text(
                    "UPDATE wallet SET balance = balance - :a "
                    "WHERE user_id=:u AND balance >= :a"
                ),
                {"a": amount, "u": user_id},
            )
            if res.rowcount == 0:
                return ReserveResult(ok=False, detail="余额不足")
            row = conn.execute(
                text("SELECT balance FROM wallet WHERE user_id=:u"), {"u": user_id}
            ).first()
            conn.execute(
                text(
                    "INSERT INTO token_ledger (user_id, task_id, model, reserve) "
                    "VALUES (:u, :t, :m, :a)"
                ),
                {"u": user_id, "t": task_id, "m": model, "a": amount},
            )
            return ReserveResult(ok=True, balance=int(row[0]) if row else None)

    def settle(
        self,
        user_id: int,
        reserved: int,
        actual: int,
        *,
        task_id: str | None = None,
        model: str | None = None,
    ) -> int:
        """结算：把 (reserved - actual) 补回余额，落 ledger；返回最新余额。

        下限保护（p6.11）：actual 可能超过 reserved（如长文档通读 token 暴涨），
        此时 refund 为负，若直接 `balance + refund` 会把余额穿成负数——而 reserve 只保证
        预扣那一刻余额够，不保证实际用量不超过预扣。用 CASE 把余额钳在 0，杜绝负余额
        （负余额会破坏 /quota 展示与后续 reserve 的 `balance>=a` 判定）。
        ledger 仍如实记录 actual，余额只表示"可消费额度"。
        """
        refund = reserved - actual
        with self.engine.begin() as conn:
            if refund:
                conn.execute(
                    text(
                        "UPDATE wallet SET balance = CASE "
                        "WHEN balance + :r < 0 THEN 0 ELSE balance + :r END "
                        "WHERE user_id=:u"
                    ),
                    {"r": refund, "u": user_id},
                )
            conn.execute(
                text(
                    "INSERT INTO token_ledger (user_id, task_id, model, reserve, settle) "
                    "VALUES (:u, :t, :m, :res, :set)"
                ),
                {"u": user_id, "t": task_id, "m": model, "res": reserved, "set": actual},
            )
            row = conn.execute(
                text("SELECT balance FROM wallet WHERE user_id=:u"), {"u": user_id}
            ).first()
            return int(row[0]) if row else 0

    def search_usage(
        self,
        user_id: int,
        *,
        model: str = "",
        start: str = "",
        end: str = "",
        min_tokens: int | None = None,
        max_tokens: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """已结算的任务用量。带上任务所在会话和提问原文，方便从账本跳回对话。"""
        from datetime import timedelta

        sql = (
            "SELECT l.task_id AS task_id, l.model AS model, l.settle AS settle, "
            "l.created_at AS created_at, t.session_id AS session_id, t.text AS question "
            "FROM token_ledger l LEFT JOIN task t ON t.id = l.task_id "
            "WHERE l.user_id = :u AND l.settle IS NOT NULL "
            "AND (l.kind IS NULL OR l.kind = 'task')"
        )
        params: dict = {"u": user_id, "l": max(1, min(int(limit), 500))}
        if model:
            sql += " AND l.model = :model"
            params["model"] = model
        if start:
            sql += " AND l.created_at >= :start"
            params["start"] = start
        if end:
            end_day = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
            sql += " AND l.created_at < :end"
            params["end"] = end_day.strftime("%Y-%m-%d")
        if min_tokens is not None:
            sql += " AND l.settle >= :min_tokens"
            params["min_tokens"] = int(min_tokens)
        if max_tokens is not None:
            sql += " AND l.settle <= :max_tokens"
            params["max_tokens"] = int(max_tokens)
        sql += " ORDER BY l.id DESC LIMIT :l"
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        out = []
        for r in rows:
            out.append(
                {
                    "task_id": r["task_id"],
                    "model": r["model"],
                    "settle": r["settle"],
                    "created_at": _iso_utc(r["created_at"]),
                    "session_id": r.get("session_id"),
                    "question": r.get("question") or "",
                }
            )
        return out

    def usage_summary(self, user_id: int) -> dict[str, int]:
        """本月（上海时区）与累计的结算用量。只计 settle 行，不含预扣。"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        start_local = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT "
                    " COALESCE(SUM(CASE WHEN settle IS NOT NULL AND created_at >= :ms THEN settle ELSE 0 END), 0), "
                    " COALESCE(SUM(CASE WHEN settle IS NOT NULL AND created_at >= :ms THEN 1 ELSE 0 END), 0), "
                    " COALESCE(SUM(CASE WHEN settle IS NOT NULL THEN settle ELSE 0 END), 0), "
                    " COALESCE(SUM(CASE WHEN settle IS NOT NULL THEN 1 ELSE 0 END), 0) "
                    "FROM token_ledger WHERE user_id=:u"
                ),
                {"ms": start_utc, "u": user_id},
            ).first()
        month_tokens, month_count, total_tokens, total_count = row or (0, 0, 0, 0)
        return {
            "month_tokens": int(month_tokens or 0),
            "month_count": int(month_count or 0),
            "total_tokens": int(total_tokens or 0),
            "total_count": int(total_count or 0),
        }
