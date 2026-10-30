"""工具层 + 兜底（p4.1）——设计文档 §四.5：能重试的重试 → 重试不了如实降级 → 降级不了转人工 → 绝不硬编答案。

- 工具报错/参数错：退避重试 ≤2 次，仍失败返回结构化错误（换等价工具/调参由上层决定）。
- 工具/能力缺失：返回 `CAPABILITY_MISSING`，**如实告知、不胡编**（§四.5）。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..core.config import settings


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str | None = None
    attempts: int = 1


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}
        self._descriptions: dict[str, str] = {}
        # v2.0.0-p1.1：OpenAI function calling 参数 Schema。None = schema_incomplete，
        # 不进 tools[] 导出（避免无 Schema 工具在 tool_calls 模式下收到乱参）。
        self._schemas: dict[str, dict[str, Any] | None] = {}

    def register(
        self,
        name: str,
        fn: Callable[..., Any],
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        if parameters is not None:
            if not isinstance(parameters, dict):
                raise ValueError(f"工具 {name} 的 parameters 必须是 JSON Schema dict")
            schema = dict(parameters)
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})
            schema.setdefault("additionalProperties", False)
            self._schemas[name] = schema
        else:
            self._schemas[name] = None
        self._tools[name] = fn
        self._descriptions[name] = description

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schema_of(self, name: str) -> dict[str, Any] | None:
        return self._schemas.get(name)

    def schema_incomplete(self) -> list[str]:
        """缺参数 Schema 的工具名（tool_calls 模式须从 tools[] 排除）。"""
        return sorted(n for n, s in self._schemas.items() if s is None)

    def describe(self) -> list[dict[str, str]]:
        """工具清单（给 LLM Brain 的提示词用）：name + description。"""
        return [
            {"name": n, "description": self._descriptions.get(n, "")}
            for n in sorted(self._tools)
        ]

    def describe_openai(self) -> list[dict[str, Any]]:
        """OpenAI 兼容 tools[]（v2.0.0-p1.1）：只导出有 Schema 的工具，名称稳定排序。"""
        out: list[dict[str, Any]] = []
        for name in sorted(self._tools):
            schema = self._schemas.get(name)
            if schema is None:
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": self._descriptions.get(name, ""),
                        "parameters": schema,
                    },
                }
            )
        return out

    def copy_into(self, other: "ToolRegistry", name: str) -> None:
        """白名单裁剪时连同 Schema 一起搬运（build_registry_for_spec 用）。"""
        other.register(
            name,
            self._tools[name],
            self._descriptions.get(name, ""),
            self._schemas.get(name),
        )

    def call(
        self,
        name: str,
        *,
        max_retries: int = 2,
        backoff: float | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """带重试的工具调用。工具缺失 → CAPABILITY_MISSING（不抛、不编）。

        p5.3：`backoff` 缺省改为读 `settings.tool_retry_backoff`（缺省 0.3s）。
        原缺省 0.0 意味着「失败后立即再打一次」，对 DB 连接抖动、对端限流这类需要
        短暂等待的瞬时错误基本无效。显式传 `backoff=0` 仍可关闭退避（测试沿用）。
        重试次数不变，因此非幂等工具的副作用风险与现状一致。
        """
        if backoff is None:
            backoff = settings.tool_retry_backoff
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
