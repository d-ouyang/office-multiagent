"""query_orders：锅圈订单的具名查询。SQL 由代码拼，模型只传字段和值。

筛选取订单表里真实存在的列（值做参数绑定，列名必须落在表结构里）。
城市不是单独的列，按门店地址包含匹配，不维护城市名单。
状态、渠道等不再用写死的可选值挡在查询前面：表里有什么值就能查什么值。
p6.46：分组统计会同步存一份可分析副本（clean_id），render_chart/analyze_table
可以直接接——"对库内业务数据聚合并可视化"这类问题不再需要文件作跳板。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .orders_seed import COLUMNS, ensure_orders_loaded
from .tools_db import _jsonable

logger = logging.getLogger(__name__)

_MAX_ROWS = 50
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SPLIT = re.compile(r"[,，、]")
# 顾客个人信息：可以按这些列筛选（值不回显到结果行），但不能出现在查询结果或分组里。
_CUSTOMER_PII = frozenset({
    "receiver_phone",
    "user_phone",
    "receiver_name",
    "user_name",
    "address",
})
_PHONE_COLUMNS = frozenset({"receiver_phone", "user_phone"})
_FILTER_OPS = frozenset({"eq", "ne", "contains", "gt", "gte", "lt", "lte", "in", "not_in"})
_EXACT_FIELDS = (
    "order_no",
    "order_status",
    "order_channel",
    "order_type",
    "fulfillment_type",
    "member_level",
    "store_id",
    "activity_id",
    "coupon_type",
    "user_gender",
    "is_coupon_used",
    "need_invoice",
)
_GROUPABLE = frozenset({"month", "city"}) | (frozenset(COLUMNS) - _CUSTOMER_PII)
_METRICS = {
    "count": "COUNT(*)",
    "sum_pay": "SUM(pay_amount)",
    "sum_total": "SUM(total_amount)",
    "sum_discount": "SUM(discount_amount)",
    "sum_refund": "SUM(refund_amount)",
    "avg_pay": "AVG(pay_amount)",
    "sum_goods": "SUM(goods_quantity)",
    "sum_goods_amount": "SUM(goods_amount)",
    "sum_delivery_fee": "SUM(delivery_fee)",
    "sum_packing_fee": "SUM(packing_fee)",
    "sum_coupon": "SUM(coupon_value)",
    "sum_points": "SUM(points_earned)",
}
METRIC_DEFINITIONS = {
    "count": "订单条数。每张订单计 1，时间按下单时间。",
    "sum_pay": "实付金额合计，字段 pay_amount。待支付和已取消的实付为 0，这些订单仍计入。",
    "sum_total": "总金额合计，字段 total_amount，等于商品小计加配送费加包装费，还没扣优惠。",
    "sum_discount": "优惠金额合计，只统计优惠券。",
    "sum_refund": "退款金额合计。已退款订单等于实付，其余为 0。",
    "avg_pay": "实付金额平均值。分母是范围内全部订单，不是只算已支付。",
    "sum_goods": "商品件数合计，字段 goods_quantity。",
    "sum_goods_amount": "商品金额合计，字段 goods_amount。",
    "sum_delivery_fee": "配送费合计，字段 delivery_fee。",
    "sum_packing_fee": "包装费合计，字段 packing_fee。",
    "sum_coupon": "券面额合计，字段 coupon_value。",
    "sum_points": "本单获得积分合计，字段 points_earned。",
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
_HIDDEN = tuple(sorted(_CUSTOMER_PII))


def _text(raw: Any) -> str:
    return str(raw or "").strip()


def _as_list(raw: Any) -> list[str]:
    """一个值、列表，或用逗号/顿号分开的多个值。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [_text(item) for item in raw if _text(item)]
    value = _text(raw)
    if not value:
        return []
    if _SPLIT.search(value):
        return [part.strip() for part in _SPLIT.split(value) if part.strip()]
    return [value]


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


def derive_city(store_address: Any) -> str:
    """从门店地址取出城市名：上海市…→上海，河南省郑州市…→郑州。没有「市」则记为其他。"""
    address = str(store_address or "")
    if "市" not in address:
        return "其他"
    head = address.split("市", 1)[0]
    if "省" in head:
        head = head.split("省", 1)[1]
    return head or "其他"


def city_like_token(city: str) -> str:
    """「上海」「上海市」都变成用于 LIKE 的地名，去掉用户自己写的通配符。"""
    name = _text(city)
    if name.endswith("市") and len(name) > 1:
        name = name[:-1]
    return name.replace("%", "").replace("_", "").replace("\\", "")


def city_expr(dialect: str) -> str:
    """与 derive_city 同一口径，供 GROUP BY 使用。"""
    if dialect == "mysql":
        head = "SUBSTRING_INDEX(store_address, '市', 1)"
        return (
            "CASE WHEN store_address IS NULL OR LOCATE('市', store_address) = 0 THEN '其他' "
            f"WHEN LOCATE('省', {head}) > 0 THEN SUBSTRING({head}, LOCATE('省', {head}) + 1) "
            f"ELSE {head} END"
        )
    head = "substr(store_address, 1, instr(store_address, '市') - 1)"
    return (
        "CASE WHEN store_address IS NULL OR instr(store_address, '市') = 0 THEN '其他' "
        f"WHEN instr({head}, '省') > 0 THEN substr({head}, instr({head}, '省') + 1) "
        f"ELSE {head} END"
    )


class _Binder:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}
        self._n = 0

    def add(self, value: Any) -> str:
        key = f"p{self._n}"
        self._n += 1
        self.params[key] = value
        return f":{key}"


def _cmp_clause(binder: _Binder, column: str, op: str, value: Any) -> str | dict[str, str]:
    if column == "city":
        if op not in {"eq", "ne", "contains", "in", "not_in"}:
            return {"error": "城市只支持 eq、ne、contains、in、not_in"}
        tokens = [city_like_token(item) for item in _as_list(value)]
        tokens = [item for item in tokens if item]
        if not tokens:
            return {"error": "城市条件为空"}
        likes = [f"store_address LIKE {binder.add(f'%{item}%')}" for item in tokens]
        joined = " OR ".join(likes)
        if op in {"ne", "not_in"}:
            return f"NOT ({joined})"
        return f"({joined})"
    if column not in COLUMNS:
        return {"error": f"没有这个字段：{column}。请用订单表里的列名。"}
    if op in {"in", "not_in"}:
        values = _as_list(value)
        if not values:
            return {"error": f"{column} 的 {op} 没有给值"}
        holders = ", ".join(binder.add(item) for item in values)
        keyword = "NOT IN" if op == "not_in" else "IN"
        return f"{column} {keyword} ({holders})"
    if op == "contains":
        token = _text(value).replace("%", "").replace("_", "").replace("\\", "")
        if not token:
            return {"error": f"{column} 的 contains 条件为空"}
        return f"{column} LIKE {binder.add(f'%{token}%')}"
    sql_op = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}.get(op)
    if sql_op is None:
        return {"error": f"不支持的过滤方式：{op}。可用 eq、ne、contains、gt、gte、lt、lte、in、not_in"}
    if isinstance(value, (list, tuple)):
        return {"error": f"{column} 的 {op} 只接受单个值；多个值请用 in 或 not_in"}
    return f"{column} {sql_op} {binder.add(value)}"


def compile_order_filters(raw: dict[str, Any], *, require_dates: bool = False) -> dict[str, Any]:
    """把具名条件和 filters 列表编成参数化 WHERE。失败时返回带 error 的字典。"""
    date_from = _date(raw.get("date_from"), "date_from")
    date_to = _date(raw.get("date_to"), "date_to")
    if isinstance(date_from, dict):
        return date_from
    if isinstance(date_to, dict):
        return date_to
    if require_dates and (not date_from or not date_to):
        return {"error": "导出必须带 date_from 和 date_to（明细导出必须有明确时间范围）"}
    if date_from and date_to and date_from > date_to:
        return {"error": "date_from 不能晚于 date_to"}

    binder = _Binder()
    clauses: list[str] = []
    applied: dict[str, Any] = {}
    if date_from:
        clauses.append(f"order_create_time >= {binder.add(f'{date_from} 00:00:00')}")
        applied["date_from"] = date_from
    if date_to:
        year, month, day = (int(part) for part in date_to.split("-"))
        nxt = datetime(year, month, day) + timedelta(days=1)
        clauses.append(f"order_create_time < {binder.add(nxt.strftime('%Y-%m-%d %H:%M:%S'))}")
        applied["date_to"] = date_to

    city = _text(raw.get("city"))
    if city:
        clause = _cmp_clause(binder, "city", "eq", city)
        if isinstance(clause, dict):
            return clause
        clauses.append(clause)
        applied["city"] = city

    store_name = _text(raw.get("store_name")).replace("%", "").replace("_", "").replace("\\", "")
    if store_name:
        clauses.append(f"store_name LIKE {binder.add(f'%{store_name}%')}")
        applied["store_name"] = store_name

    for key in _EXACT_FIELDS:
        values = _as_list(raw.get(key))
        if not values:
            continue
        op = "eq" if len(values) == 1 else "in"
        clause = _cmp_clause(binder, key, op, values if op == "in" else values[0])
        if isinstance(clause, dict):
            return clause
        clauses.append(clause)
        applied[key] = values[0] if len(values) == 1 else values

    excluded = _as_list(raw.get("exclude_status"))
    if excluded:
        op = "ne" if len(excluded) == 1 else "not_in"
        clause = _cmp_clause(binder, "order_status", op, excluded if op == "not_in" else excluded[0])
        if isinstance(clause, dict):
            return clause
        clauses.append(clause)
        applied["exclude_status"] = excluded[0] if len(excluded) == 1 else excluded

    extra = raw.get("filters")
    if extra:
        items = extra if isinstance(extra, list) else [extra]
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                return {"error": f"filters[{index}] 必须是 {{column, op, value}}"}
            column = _text(item.get("column"))
            op = _text(item.get("op")) or "eq"
            if op not in _FILTER_OPS:
                return {"error": f"不支持的过滤方式：{op}。可用 {'、'.join(sorted(_FILTER_OPS))}"}
            clause = _cmp_clause(binder, column, op, item.get("value"))
            if isinstance(clause, dict):
                return clause
            clauses.append(clause)
        if items:
            applied["filters"] = items

    return {"clauses": clauses, "params": binder.params, "applied": applied}


def make_query_orders_tool(
    engine: Engine | None, *, max_rows: int = _MAX_ROWS, base_dir: str | None = None
) -> Callable[..., Any]:
    def query_orders(**raw: Any) -> dict[str, Any]:
        if engine is None:
            return {"error": "数据库不可用：未配置数据库连接"}
        loaded = ensure_orders_loaded(engine)
        if loaded == "missing":
            return {"error": "订单表还没有建立"}
        if loaded == "empty-no-csv":
            return {"error": "订单表是空的，且没有找到可导入的 CSV"}

        built = compile_order_filters(raw)
        if built.get("error"):
            return built
        clauses = built["clauses"]
        params = built["params"]
        applied = built["applied"]

        group_by = _text(raw.get("group_by"))
        if group_by and group_by not in _GROUPABLE:
            return {
                "error": (
                    f"不能按 {group_by} 分组。可以用 month、city，"
                    "或订单表里除手机号、真实姓名、收货地址以外的字段。"
                )
            }
        metric = _text(raw.get("metric")) or ("sum_pay" if group_by else "")
        if metric and metric not in _METRICS:
            return {"error": f"metric 只能是 {'、'.join(_METRICS)}"}
        limit = min(max_rows, _limit(raw.get("limit")))

        if not clauses and not group_by and not metric:
            return {"error": "查询必须带时间、城市、门店、字段筛选或分组，避免整表读取"}

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        dialect = engine.dialect.name
        hint = "/*+ MAX_EXECUTION_TIME(3000) */ " if dialect == "mysql" else ""
        if group_by or (metric and "order_no" not in applied):
            if group_by == "city":
                label = city_expr(dialect)
            elif group_by == "month":
                label = _month_expr(dialect)
            else:
                label = group_by
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
            # p6.46：分组结果存一份可分析副本（clean_id）——"按 X 统计再画图/再分析"这类
            # 问题不再需要先有文件；render_chart / analyze_table 直接吃这个 clean_id。
            chart_id = None
            if group_by and rows and base_dir:
                try:
                    from .tools_table import _write_clean

                    cols = ["grp", "order_count", "metric_value"]
                    chart_id = _write_clean(
                        Path(base_dir),
                        cols,
                        [[str(r.get(c, "")) for c in cols] for r in rows],
                        {
                            "source": "query_orders",
                            "group_by": group_by,
                            "metric": metric or "count",
                            "filters": applied,
                            "rows": len(rows),
                        },
                    )
                except Exception:  # noqa: BLE001 - 存副本失败不影响查询本身
                    logger.exception("query_orders 分组结果存副本失败")
            return {
                "filters": applied,
                "group_by": group_by or None,
                "metric": metric or "count",
                "scope": "全部已入库订单" if not applied else "按筛选汇总",
                "truncated": bool(group_by) and len(rows) >= limit,
                "row_count": len(rows),
                "rows": rows,
                "clean_id": chart_id,
                "chart_hint": (
                    f"要画图或再分析：把 clean_id 交给 render_chart（x=grp，y=metric_value 或 order_count）/ analyze_table"
                    if chart_id
                    else None
                ),
            }

        requested = _as_list(raw.get("columns"))
        if requested:
            unknown = [name for name in requested if name not in COLUMNS]
            hidden = [name for name in requested if name in _CUSTOMER_PII]
            if unknown:
                return {"error": f"没有这些字段：{'、'.join(unknown)}。请用订单表列名。"}
            if hidden:
                return {
                    "error": (
                        f"查询结果不返回个人信息：{'、'.join(hidden)}。"
                        "要带脱敏手机号的明细文件请用 export_orders。"
                    )
                }
            columns = tuple(dict.fromkeys(requested))
        else:
            columns = _LIST_COLUMNS + (_DETAIL_EXTRA if "order_no" in applied else ())
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
