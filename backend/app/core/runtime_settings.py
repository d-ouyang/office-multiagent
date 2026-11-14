"""个人中心里能改的运行时设置。

只收「改了会改变产品行为、而且应该让人看见」的项。连接池、密钥、超时不进这里。

作用域：
- system：全员一份。管理员改，下一次任务就按新值走；员工只能看。
- 个人偏好（当前模型、回答力度）不进这张表，它们记在会话和当次发送上。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from .config import settings

logger = logging.getLogger(__name__)

_loaded = False
_values: dict[str, str] = {}


def _catalog() -> dict[str, dict[str, Any]]:
    return {
        "task_token_hard_limit": {
            "label": "单任务 token 上限",
            "description": "一次任务最多消耗这么多 token。到上限后停在下一次模型调用之前，已经得到的结果保留。填 0 表示不设上限。对所有用户生效，和钱包余额无关。",
            "value_type": "int",
            "scope": "system",
            "min": 0,
            "max": 2_000_000,
            "default": int(settings.task_token_hard_limit),
        },
        "result_validation": {
            "label": "结果数字校验",
            "description": "终答里的数字对不上工具结果时，在过程里提示核对，不拦截回答。对所有用户生效。",
            "value_type": "bool",
            "scope": "system",
            "default": bool(settings.result_validation),
        },
        # v2.2.0-p1.6（B3）：三级硬预算的 tenant 级 + 循环护栏开关
        "tenant_daily_token_budget": {
            "label": "全站当日 token 预算",
            "description": "所有用户当日（UTC 日）结算量之和的上限。达到后新任务在入口直接拒绝（429），明日自动恢复；0 表示不设限。软告警在用量达预算 80% 时发一次 webhook（如已配置）。",
            "value_type": "int",
            "scope": "system",
            "min": 0,
            "max": 100_000_000,
            "default": 0,
        },
        "agent_max_iterations": {
            "label": "Agent 循环步数上限",
            "description": "单 Agent ReAct 循环最多执行多少步，超限强制基于已有观察收尾（防跑飞烧钱）。3~50。",
            "value_type": "int",
            "scope": "system",
            "min": 3,
            "max": 50,
            "default": int(settings.agent_max_iterations),
        },
    }


def _engine():
    from .db import get_engine

    return get_engine()


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with _engine().connect() as conn:
            rows = conn.execute(
                text("SELECT setting_key, setting_value FROM runtime_setting")
            ).all()
    except Exception:  # noqa: BLE001 - 表还没迁移时回落到环境变量，不阻断任务
        logger.debug("读取运行时设置失败，使用环境变量默认值", exc_info=True)
        return
    for key, value in rows:
        if value is not None:
            _values[str(key)] = str(value)


def _read_raw(key: str) -> str | None:
    _ensure_loaded()
    return _values.get(key)


def _coerce(spec: dict[str, Any], raw: str | None) -> Any:
    if raw is None or raw == "":
        return spec["default"]
    if spec["value_type"] == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    try:
        value = int(raw)
    except ValueError:
        return spec["default"]
    return max(int(spec["min"]), min(int(spec["max"]), value))


def effective(key: str) -> Any:
    spec = _catalog().get(key)
    if spec is None:
        raise KeyError(key)
    return _coerce(spec, _read_raw(key))


def task_token_limit() -> int:
    return int(effective("task_token_hard_limit"))


def result_validation_enabled() -> bool:
    return bool(effective("result_validation"))


def public_items() -> list[dict[str, Any]]:
    items = []
    for key, spec in _catalog().items():
        items.append(
            {
                "key": key,
                "label": spec["label"],
                "description": spec["description"],
                "value_type": spec["value_type"],
                "scope": spec["scope"],
                "value": effective(key),
                "min": spec.get("min"),
                "max": spec.get("max"),
            }
        )
    return items


def validate_and_store(key: str, value: Any) -> Any:
    spec = _catalog().get(key)
    if spec is None:
        raise KeyError(key)
    if spec["value_type"] == "bool":
        if isinstance(value, str):
            stored = value.strip().lower() in ("1", "true", "yes", "on")
        else:
            stored = bool(value)
        raw = "1" if stored else "0"
        saved: Any = stored
    else:
        try:
            number = int(value)
        except (TypeError, ValueError) as e:
            raise ValueError("需要整数") from e
        if number < int(spec["min"]) or number > int(spec["max"]):
            raise ValueError(f"需要在 {spec['min']} 到 {spec['max']} 之间")
        raw = str(number)
        saved = number
    with _engine().begin() as conn:
        existing = conn.execute(
            text("SELECT setting_key FROM runtime_setting WHERE setting_key = :k"),
            {"k": key},
        ).first()
        if existing:
            conn.execute(
                text("UPDATE runtime_setting SET setting_value = :v WHERE setting_key = :k"),
                {"k": key, "v": raw},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO runtime_setting (setting_key, setting_value) VALUES (:k, :v)"
                ),
                {"k": key, "v": raw},
            )
    global _loaded
    _loaded = True
    _values[key] = raw
    return saved
