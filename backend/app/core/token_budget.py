"""单任务 token 硬上限。

与钱包不同：钱包在任务开始前判断「付不付得起」；本模块在任务运行中限制一次任务
最多还能发起多少模型调用。所有用户共用同一个配置值，但每个任务有独立预算实例。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


class TokenLimitReached(RuntimeError):
    """剩余额度不足以安全发起下一次模型调用。"""


@dataclass
class TokenReservation:
    budget: "TaskTokenBudget"
    allocated: int
    max_output_tokens: int
    closed: bool = False

    def complete(self, actual: int) -> None:
        if self.closed:
            return
        self.closed = True
        self.budget._finish(self.allocated, max(0, int(actual)))  # noqa: SLF001

    def cancel(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.budget._finish(self.allocated, 0)  # noqa: SLF001


class TaskTokenBudget:
    """线程安全；支持 multi 同层并发提前占位，防止几个 Agent 同时冲穿上限。"""

    def __init__(self, limit: int) -> None:
        self.limit = max(0, int(limit))
        self.used = 0
        self.reserved = 0
        self.limit_reached = False
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    @property
    def remaining(self) -> int:
        if not self.enabled:
            return 2**31 - 1
        with self._lock:
            return max(0, self.limit - self.used - self.reserved)

    @staticmethod
    def prompt_upper_bound(messages: list[dict[str, Any]]) -> int:
        """UTF-8 字节数是常见 BPE tokenizer 的保守 token 上界，再留协议余量。"""
        size = sum(
            len(str(item.get("role") or "").encode("utf-8"))
            + len(str(item.get("content") or "").encode("utf-8"))
            for item in messages
        )
        return size + 64

    def reserve_call(
        self,
        messages: list[dict[str, Any]],
        *,
        desired_output_tokens: int = 8192,
    ) -> TokenReservation | None:
        if not self.enabled:
            return None
        prompt_cap = self.prompt_upper_bound(messages)
        with self._lock:
            available = self.limit - self.used - self.reserved
            output_cap = min(max(1, int(desired_output_tokens)), available - prompt_cap)
            if output_cap <= 0:
                self.limit_reached = True
                raise TokenLimitReached(
                    f"单次任务 token 上限为 {self.limit}，剩余 {max(0, available)}，"
                    "不足以安全发起下一次模型调用"
                )
            allocated = prompt_cap + output_cap
            self.reserved += allocated
        return TokenReservation(self, allocated, output_cap)

    def _finish(self, allocated: int, actual: int) -> None:
        with self._lock:
            self.reserved = max(0, self.reserved - allocated)
            self.used += actual
            if self.used >= self.limit:
                self.limit_reached = True

    def renew(self) -> None:
        """2.1.0：budget 暂停后续跑时重置预算（用户确认继续 = 授予新一轮额度）。
        任务级上限是防 runaway 的护栏，不是钱包扣费（真钱在钱包 settle）；重置合理。"""
        with self._lock:
            self.used = 0
            self.reserved = 0
            self.limit_reached = False

    def consume_external(self, tokens: int) -> None:
        """记录外部工作流返回的实际用量；它无法在本进程内提前限制单次响应。"""
        amount = max(0, int(tokens))
        if not amount or not self.enabled:
            return
        with self._lock:
            self.used += amount
            if self.used >= self.limit:
                self.limit_reached = True
