"""预算软告警（v2.2.0-p1.6 / B3）——预算触达比例时 POST webhook，fire-and-forget。

硬约束（429 短路）在入口预检；本模块只做「让人知道快到墙了」：后台线程 5s 超时
POST JSON，失败仅日志（告警失败绝不影响任务）。当日（UTC）同 kind 只发一次——
进程内存去重，重启后重发一次可接受（告警宁多勿漏）。
URL 来自 settings.budget_alert_webhook_url（空 = 关闭）；payload 为通用 JSON
（兼容企业微信/钉钉/Slack 的 Incoming Webhook 需要各自包装时，在 url 侧挂转换服务）。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from .config import settings

logger = logging.getLogger(__name__)

_alerted: dict[str, str] = {}  # kind -> UTC 日期（当日去重）
_lock = threading.Lock()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def fire_budget_alert(kind: str, detail: dict) -> None:
    """预算告警入口：当日同 kind 去重；未配置 webhook 直接返回。"""
    url = str(settings.budget_alert_webhook_url or "").strip()
    if not url:
        return
    with _lock:
        if _alerted.get(kind) == _today():
            return
        _alerted[kind] = _today()

    payload = {"kind": kind, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "detail": detail}

    def _post() -> None:
        try:
            import httpx

            # trust_env=False：告警目标通常是内网 webhook，不吃系统代理
            r = httpx.post(url, json=payload, timeout=5.0, trust_env=False)
            logger.info("预算软告警已发送 kind=%s status=%d", kind, r.status_code)
        except Exception as e:  # noqa: BLE001 - 告警失败仅日志，绝不影响任务
            logger.warning("预算软告警发送失败 kind=%s: %s", kind, e)

    threading.Thread(target=_post, daemon=True, name=f"budget-alert-{kind}").start()
