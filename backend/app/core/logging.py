"""结构化日志 + 请求链路追踪（设计文档 §十八 日志与可观测性）。

要点：
  · 默认 JSON 行日志（便于远端集中采集 / 检索）；本地调试可切 text。
  · 每个请求一个 correlation_id（取 X-Request-ID，没有则生成），
    通过 contextvars 注入到该请求所有日志，便于跨服务串联。
  · 预留 agent_step / token_audit / log_duration 三个语义化辅助函数，
    供后续 Phase 4（多 Agent 协调）/ Phase 6（token 池对账）直接调用，
    保证「算数交给代码、LLM 只做推理」的可追溯性（设计文档 §十一）。
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import settings

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get() or "-"
        return True


# LogRecord 自带的属性，不能摊进 JSON payload（会与格式化冲突）
_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "msg", "message", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info", "thread",
    "threadName", "correlation_id",
}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # 把 extra 里的结构化字段摊平进来（跳过保留字）
        for key, val in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = val
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    if settings.log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
    handler.addFilter(_CorrelationFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    # 第三方库降噪，避免淹没业务日志
    logging.getLogger("uvicorn.access").setLevel("WARNING")


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = _correlation_id.set(cid)
        request.state.correlation_id = cid
        try:
            response = await call_next(request)
        finally:
            _correlation_id.reset(token)
        response.headers["X-Request-ID"] = cid
        return response


# ---- 语义化辅助（供 Agent / token 链路调用）----


def log_agent_step(subtask_id: str, agent: str, action: str, **fields: Any) -> None:
    """记录一个 Agent 步骤（Phase 4 调度 / 兜底时调用）。"""
    logging.getLogger("agent").info(
        "agent_step",
        extra={"subtask_id": subtask_id, "agent": agent, "action": action, **fields},
    )


def log_token_audit(
    user_id: int, model: str, reserve: int = 0, settle: int = 0, **fields: Any
) -> None:
    """记录一次 token 预扣/结算（Phase 6 两段式扣减对账时调用）。"""
    logging.getLogger("token").info(
        "token_audit",
        extra={
            "user_id": user_id,
            "model": model,
            "reserve": reserve,
            "settle": settle,
            **fields,
        },
    )


def log_duration(logger_name: str, span: str, start: float, **fields: Any) -> None:
    """记录一段耗时（毫秒）。

    ⚠️ 字段名用 `span` 而非 `name`：`name` 是 LogRecord 的保留属性，
    放进 extra 会直接 KeyError（被 test_connection 抓到的真实 bug）。
    """
    logging.getLogger(logger_name).info(
        "duration",
        extra={"span": span, "ms": int((time.time() - start) * 1000), **fields},
    )
