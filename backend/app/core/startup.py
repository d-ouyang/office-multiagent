"""启动期连接预热 + 重试（p1.2a）。

compose 里 backend 虽 depends_on mysql/redis healthy，但跨机 / 共享中间件 /
网络抖动仍可能让首次连接失败。这里在 app 启动时按线性退避重试探测三件套，
拿一份探活报告。**刻意不杀进程**：mysql/redis 未就绪就降级运行、由 /health
暴露问题，之后每次请求凭 pool_pre_ping / health_check_interval 自愈重连
（否掉「启动即 kill 容器」方案——compose 会反复重启且丢失现场，见迭代文档 §3）。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from . import chroma_client, db, redis_client
from .config import settings
from .logging import log_duration

PingFn = Callable[[], tuple[bool, str | None]]


def _retry_ping(fn: PingFn, retries: int, backoff: float) -> tuple[bool, str | None, int]:
    """线性退避重试探测；返回 (ok, detail, 实际尝试次数)。"""
    last: str | None = None
    for attempt in range(1, retries + 1):
        ok, detail = fn()
        if ok:
            return True, None, attempt
        last = detail
        if attempt < retries:
            time.sleep(backoff * attempt)
    return False, last, retries


def warmup_connections() -> dict[str, dict[str, Any]]:
    """探测三件套，返回 {name: {ok, detail}}。chroma 缺失不致命。"""
    start = time.time()
    retries = settings.connect_max_retries
    backoff = settings.connect_retry_backoff
    my_ok, my_err, _ = _retry_ping(db.ping_mysql, retries, backoff)
    rd_ok, rd_err, _ = _retry_ping(redis_client.ping_redis, retries, backoff)
    ch_ok, ch_err, _ = _retry_ping(chroma_client.ping_chroma, retries, backoff)
    report = {
        "mysql": {"ok": my_ok, "detail": my_err},
        "redis": {"ok": rd_ok, "detail": rd_err},
        "chroma": {"ok": ch_ok, "detail": ch_err},
    }
    log_duration(
        "startup",
        "warmup_connections",
        start,
        mysql=my_ok,
        redis=rd_ok,
        chroma=ch_ok,
    )
    return report
