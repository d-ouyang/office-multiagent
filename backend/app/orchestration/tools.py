"""工具层 + 兜底（p4.1）——设计文档 §四.5：能重试的重试 → 重试不了如实降级 → 降级不了转人工 → 绝不硬编答案。

- 工具报错/参数错：退避重试 ≤2 次，仍失败返回结构化错误（换等价工具/调参由上层决定）。
- 工具/能力缺失：返回 `CAPABILITY_MISSING`，**如实告知、不胡编**（§四.5）。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str | None = None
    attempts: int = 1


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def call(
        self,
        name: str,
        *,
        max_retries: int = 2,
        backoff: float = 0.0,
        **kwargs: Any,
    ) -> ToolResult:
        """带重试的工具调用。工具缺失 → CAPABILITY_MISSING（不抛、不编）。"""
        fn = self._tools.get(name)
        if fn is None:
            return ToolResult(
                ok=False, error=f"CAPABILITY_MISSING: 暂无工具 {name}", attempts=0
            )
        last: Exception | None = None
        for attempt in range(1, max_retries + 2):  # 首次 + 最多 max_retries 次重试
            try:
                return ToolResult(ok=True, output=fn(**kwargs), attempts=attempt)
            except Exception as e:  # noqa: BLE001 - 工具异常要兜住降级，不炸编排
                last = e
                if attempt <= max_retries and backoff:
                    time.sleep(backoff * attempt)
        return ToolResult(ok=False, error=str(last), attempts=max_retries + 1)
