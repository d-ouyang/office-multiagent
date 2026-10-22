"""query_orders：锅圈订单的具名查询。SQL 写死，模型只传白名单参数。"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .orders_seed import ensure_orders_loaded
from .tools_db import _jsonable

_MAX_ROWS = 50
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATUSES = ("已完成", "已支付", "配送中", "已退款", "待支付", "已取消")
_CHANNELS = ("微信小程序", "抖音小程序", "门店扫码", "美团外卖", "饿了么外卖")
_TYPES = ("普通订单", "拼团订单", "接龙订单")
_FULFILLMENT = ("门店自提", "同城配送", "平台外卖配送")
_LEVELS = ("普通会员", "银卡会员", "金卡会员", "黑金会员")
_CITIES = {"上海": "上海市%", "安庆": "安庆市%"}
_GROUPS = (
    "month",
    "store_name",
    "order_channel",
    "order_status",
    "order_type",
    "fulfillment_type",
    "member_level",
    "city",
)
_METRICS = {
    "count": "COUNT(*)",
    "sum_pay": "SUM(pay_amount)",
    "sum_total": "SUM(total_amount)",
    "sum_discount": "SUM(discount_amount)",
    "sum_refund": "SUM(refund_amount)",
    "avg_pay": "AVG(pay_amount)",
    "sum_goods": "SUM(goods_quantity)",
}
_LIST_COLUMNS = (
    "order_no",
    "order_create_time",
    "order_status",
    "order_type",
    "order_channel",
    "store_name",
    "fulfillment_type",
    "goods_quantity",
    "pay_amount",
    "total_amount",
    "discount_amount",
    "member_level",
)
_DETAIL_EXTRA = (
    "goods_list",
    "coupon_type",
    "coupon_name",
    "refund_amount",
    "order_remark",
    "points_earned",
    "is_coupon_used",
    "need_invoice",
    "activity_name",
)
_HIDDEN = ("receiver_phone", "user_phone", "receiver_name", "user_name", "address", "store_phone")


def _text(raw: Any) -> str:
    return str(raw or "").strip()


def _date(raw: Any, label: str) -> str | dict[str, str]:
    value = _text(raw)
    if not value:
        return ""
    if not _DATE.match(value):
        return {"error": f"{label} 必须是 YYYY-MM-DD"}
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return {"error": f"{label} 不是有效日期"}
    return value


def _choice(raw: Any, label: str, allowed: tuple[str, ...]) -> str | dict[str, str]:
    value = _text(raw)
    if not value:
        return ""
    if value not in allowed:
        return {"error": f"没有这个{label}：{value}。可选：{'、'.join(allowed)}"}
    return value


def _limit(raw: Any) -> int:
    try:
        number = int(raw)
    except (TypeError, ValueError):
        number = 20
    return min(_MAX_ROWS, max(1, number))


def _month_expr(dialect: str) -> str:
    if dialect == "mysql":
        return "DATE_FORMAT(order_create_time, '%Y-%m')"
    return "strftime('%Y-%m', order_create_time)"


def _city_expr() -> str:
    return (
        "CASE WHEN store_address LIKE '上海市%' THEN '上海' "
        "WHEN store_address LIKE '安庆市%' THEN '安庆' ELSE '其他' END"
    )


def make_query_orders_tool(engine: Engine | None, *, max_rows: int = _MAX_ROWS) -> Callable[..., Any]:
    def query_orders(**raw: Any) -> dict[str, Any]:
        if engine is None:
            return {"error": "数据库不可用：未配置数据库连接"}
        loaded = ensure_orders_loaded(engine)
        if loaded == "missing":
            return {"error": "订单表还没有建立"}
        if loaded == "empty-no-csv":
            return {"error": "订单表是空的，且没有找到可导入的 CSV"}

        date_from = _date(raw.get("date_from"), "date_from")
        date_to = _date(raw.get("date_to"), "date_to")
        status = _choice(raw.get("order_status"), "订单状态", _STATUSES)
        channel = _choice(raw.get("order_channel"), "订单渠道", _CHANNELS)
        order_type = _choice(raw.get("order_type"), "订单类型", _TYPES)
        fulfillment = _choice(raw.get("fulfillment_type"), "履约方式", _FULFILLMENT)
        level = _choice(raw.get("member_level"), "会员等级", _LEVELS)
        for item in (date_from, date_to, status, channel, order_type, fulfillment, level):
            if isinstance(item, dict):
                return item

        city = _text(raw.get("city"))
        if city and city not in _CITIES:
            return {"error": f"没有这个城市：{city}。可选：上海、安庆"}
        group_by = _text(raw.get("group_by"))
        if group_by and group_by not in _GROUPS:
            return {"error": f"group_by 只能是 {'、'.join(_GROUPS)}"}
        metric = _text(raw.get("metric")) or ("sum_pay" if group_by else "")
        if metric and metric not in _METRICS:
            return {"error": f"metric 只能是 {'、'.join(_METRICS)}"}
        order_no = _text(raw.get("order_no"))
        store_name = _text(raw.get("store_name")).replace("%", "").replace("_", "")
        limit = min(max_rows, _limit(raw.get("limit")))

        filters: list[str] = []
        params: dict[str, Any] = {}
        applied: dict[str, str] = {}
        if date_from:
            filters.append("order_create_time >= :date_from")
            params["date_from"] = f"{date_from} 00:00:00"
            applied["date_from"] = date_from
        if date_to:
            filters.append("order_create_time < :date_to_next")
            year, month, day = (int(part) for part in str(date_to).split("-"))
            nxt = datetime(year, month, day)
            params["date_to_next"] = (nxt + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            applied["date_to"] = date_to
        if order_no:
            filters.append("order_no = :order_no")
            params["order_no"] = order_no
            applied["order_no"] = order_no
        if store_name:
            filters.append("store_name LIKE :store_name")
            params["store_name"] = f"%{store_name}%"
            applied["store_name"] = store_name
        if city:
            filters.append("store_address LIKE :city")
            params["city"] = _CITIES[city]
            applied["city"] = city
        for key, value in (
            ("order_status", status),
            ("order_channel", channel),
            ("order_type", order_type),
            ("fulfillment_type", fulfillment),
            ("member_level", level),
        ):
            if value:
                filters.append(f"{key} = :{key}")
                params[key] = value
                applied[key] = str(value)

        if not filters and not group_by and not metric:
            return {"error": "查询必须带时间、城市、门店、渠道、状态或分组，避免整表读取"}

        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        dialect = engine.dialect.name
        hint = "/*+ MAX_EXECUTION_TIME(3000) */ " if dialect == "mysql" else ""
        if group_by or (metric and not order_no):
            label = _city_expr() if group_by == "city" else _month_expr(dialect) if group_by == "month" else group_by
            metric_sql = _METRICS[metric or "count"]
            if group_by:
                sql = (
                    f"SELECT {hint}{label} AS grp, COUNT(*) AS order_count, {metric_sql} AS metric_value "
                    f"FROM guoquan_orders{where} GROUP BY {label} ORDER BY metric_value DESC LIMIT {limit}"
                )
            else:
                sql = (
                    f"SELECT {hint}COUNT(*) AS order_count, {metric_sql} AS metric_value "
                    f"FROM guoquan_orders{where}"
                )
            rows = _run(engine, sql, params)
            return {
                "filters": applied,
                "group_by": group_by or None,
                "metric": metric or "count",
                "scope": "全部已入库订单" if not applied else "按筛选汇总",
                "truncated": bool(group_by) and len(rows) >= limit,
                "row_count": len(rows),
                "rows": rows,
            }

        columns = _LIST_COLUMNS + (_DETAIL_EXTRA if order_no else ())
        count_sql = f"SELECT COUNT(*) AS n FROM guoquan_orders{where}"
        total = int(_run(engine, count_sql, params)[0]["n"])
        sql = (
            f"SELECT {hint}{', '.join(columns)} FROM guoquan_orders{where} "
            f"ORDER BY order_create_time DESC LIMIT {limit}"
        )
        rows = _run(engine, sql, params)
        return {
            "filters": applied,
            "truncated": total > len(rows),
            "total_matched": total,
            "row_count": len(rows),
            "rows": rows,
            "omitted": list(_HIDDEN),
        }

    query_orders.__name__ = "query_orders"
    return query_orders


def _run(engine: Engine, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        return [{key: _jsonable(value) for key, value in dict(row).items()} for row in result.mappings().all()]
