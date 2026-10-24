"""compare_orders：同比、环比、占比。数字只来自 query_orders，比率由代码算。"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.engine import Engine

from .tools_orders import make_query_orders_tool

_MODES = {"mom", "yoy", "share"}
_PASS = (
    "city",
    "store_name",
    "order_status",
    "exclude_status",
    "order_channel",
    "order_type",
    "fulfillment_type",
    "member_level",
    "filters",
)


def _shift_year(day: datetime, years: int) -> datetime:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def _num(raw: Any) -> float:
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _ratio(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / abs(previous), 4)


def make_compare_orders_tool(engine: Engine | None) -> Callable[..., Any]:
    query = make_query_orders_tool(engine)

    def compare_orders(
        date_from: str,
        date_to: str,
        metric: str = "sum_pay",
        mode: str = "mom",
        group_by: str | None = None,
        **raw: Any,
    ) -> dict[str, Any]:
        how = (mode or "mom").strip().lower()
        if how not in _MODES:
            return {"error": "mode 只能是 mom（环比）、yoy（同比）或 share（占比）"}
        try:
            start = datetime.strptime(str(date_from), "%Y-%m-%d")
            end = datetime.strptime(str(date_to), "%Y-%m-%d")
        except ValueError:
            return {"error": "date_from 和 date_to 必须是 YYYY-MM-DD"}
        if end < start:
            return {"error": "date_from 不能晚于 date_to"}

        base: dict[str, Any] = {"metric": metric}
        if group_by:
            base["group_by"] = group_by
        for key in _PASS:
            if raw.get(key) not in (None, "", []):
                base[key] = raw[key]

        if how == "share":
            if not group_by:
                return {"error": "占比必须带 group_by，例如 store_name 或 order_channel"}
            current = query(date_from=date_from, date_to=date_to, **base)
            if current.get("error"):
                return current
            rows = current.get("rows") or []
            total = sum(_num(row.get("metric_value")) for row in rows)
            compared = []
            for row in rows:
                value = _num(row.get("metric_value"))
                compared.append({
                    "group": row.get("grp"),
                    "current": value,
                    "share": round(value / total, 4) if total else None,
                })
            return {
                "mode": "share",
                "metric": metric,
                "group_by": group_by,
                "date_from": date_from,
                "date_to": date_to,
                "total": round(total, 4),
                "rows": compared,
                "note": "占比 = 该组指标 / 各组指标之和，由代码计算，不是模型估算。",
            }

        span = (end - start).days + 1
        if how == "yoy":
            prev_start, prev_end = _shift_year(start, -1), _shift_year(end, -1)
        else:
            prev_end = start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=span - 1)
        current = query(date_from=date_from, date_to=date_to, **base)
        if current.get("error"):
            return current
        previous = query(
            date_from=prev_start.strftime("%Y-%m-%d"),
            date_to=prev_end.strftime("%Y-%m-%d"),
            **base,
        )
        if previous.get("error"):
            return previous

        def index(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
            found: dict[str, dict[str, Any]] = {}
            for row in result.get("rows") or []:
                key = str(row.get("grp") if group_by else "全部")
                found[key] = row
            if not found and not group_by:
                found["全部"] = {"order_count": 0, "metric_value": 0}
            return found

        left, right = index(current), index(previous)
        compared = []
        for key in list(dict.fromkeys([*left, *right])):
            cur = _num((left.get(key) or {}).get("metric_value"))
            prev = _num((right.get(key) or {}).get("metric_value"))
            compared.append({
                "group": None if key == "全部" and not group_by else key,
                "current": cur,
                "previous": prev,
                "delta": round(cur - prev, 4),
                "ratio": _ratio(cur, prev),
            })
        label = "同比" if how == "yoy" else "环比"
        return {
            "mode": how,
            "label": label,
            "metric": metric,
            "group_by": group_by or None,
            "current_range": f"{date_from} 至 {date_to}",
            "previous_range": f"{prev_start.strftime('%Y-%m-%d')} 至 {prev_end.strftime('%Y-%m-%d')}",
            "rows": compared,
            "note": (
                f"{label}由代码按两段 query_orders 结果相减。"
                "ratio 为空表示上期为 0，不能算变化率，不要自己补一个百分比。"
            ),
        }

    compare_orders.__name__ = "compare_orders"
    return compare_orders
