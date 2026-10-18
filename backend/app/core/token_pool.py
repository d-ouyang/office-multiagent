"""Token 池两段式扣减（p4.2）——设计文档 §十四：reserve 预扣 + settle 结算，原子防并行超额。

- reserve：原子 `UPDATE wallet SET balance=balance-:a WHERE user_id=:u AND balance>=:a`，
  影响行数 0 即余额不足 → 拒绝（防并行子 Agent 超额，§十四）。
- settle：按实际用量补差 `reserved - actual`（可正可负），落 `token_ledger`。
- 引擎可注入：生产 MySQL、测试 SQLite 内存——同一条参数化原子 SQL 两边都成立。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine


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
        """结算：把 (reserved - actual) 补回余额，落 ledger；返回最新余额。"""
        refund = reserved - actual
        with self.engine.begin() as conn:
            if refund:
                conn.execute(
                    text("UPDATE wallet SET balance = balance + :r WHERE user_id=:u"),
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
