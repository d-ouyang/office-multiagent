"""销售报表模板。时间范围、指标、口径、数据来源缺一项就不算完成。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import Engine

from .tools_orders import METRIC_DEFINITIONS, make_query_orders_tool

_SOURCE = "锅圈食汇订单表 guoquan_orders。本次数字只来自 query_orders，不是模型计算。"
_FILTER_LABELS = {
    "city": "城市",
    "store_name": "门店",
    "order_status": "订单状态",
    "exclude_status": "排除状态",
    "order_channel": "渠道",
    "order_type": "订单类型",
    "fulfillment_type": "履约方式",
    "member_level": "会员等级",
    "group_by": "分组",
}
_PASS = (
    "city",
    "store_name",
    "order_status",
    "exclude_status",
    "order_channel",
    "order_type",
    "fulfillment_type",
    "member_level",
    "group_by",
)


def _text(raw: Any) -> str:
    return str(raw or "").strip()


def _incomplete(missing: list[str], error: str) -> dict[str, Any]:
    return {"complete": False, "missing": missing, "report": None, "error": error}


def make_sales_report_tool(engine: Engine | None) -> Callable[..., Any]:
    query = make_query_orders_tool(engine)

    def sales_report(**raw: Any) -> dict[str, Any]:
        date_from = _text(raw.get("date_from"))
        date_to = _text(raw.get("date_to"))
        metric = _text(raw.get("metric"))
        missing: list[str] = []
        if not date_from or not date_to:
            missing.append("时间范围")
        if not metric or metric not in METRIC_DEFINITIONS:
            missing.append("指标")
        if missing:
            return _incomplete(missing, "时间范围、指标、口径、数据来源缺一项，报表不能当作完成")

        asked = {"date_from": date_from, "date_to": date_to, "metric": metric}
        for key in _PASS:
            value = _text(raw.get(key))
            if value:
                asked[key] = value
        result = query(**asked)
        if result.get("error"):
            return _incomplete(["数据来源"], str(result["error"]))
        if result.get("truncated"):
            return _incomplete(["完整结果"], "分组结果被截断，报表不能当作完成")

        filters = result.get("filters") or {}
        extra = [
            f"{_FILTER_LABELS[key]}={filters[key]}"
            for key in _FILTER_LABELS
            if key in filters and key != "group_by"
        ]
        scope = "；".join(extra) if extra else "只按时间范围，没有再加城市、状态或渠道"
        definition = (
            f"{METRIC_DEFINITIONS[metric]} 时间含 {date_from} 至 {date_to} 当天，按下单时间。"
            f"筛选：{scope}。"
        )
        if filters.get("group_by") or asked.get("group_by"):
            definition += f"分组：{asked.get('group_by') or filters.get('group_by')}。"

        numbers = [
            {
                "group": row.get("grp"),
                "order_count": row.get("order_count"),
                "metric_value": row.get("metric_value"),
            }
            for row in result.get("rows") or []
        ]
        lines = [
            "销售报表",
            "状态：完成",
            f"时间范围：{date_from} 至 {date_to}",
            f"指标：{metric}",
            f"口径：{definition}",
            f"数据来源：{_SOURCE}",
            "结果：",
        ]
        if not numbers:
            lines.append("- 没有匹配的订单。订单数 0。")
        for item in numbers:
            label = f"{item['group']}：" if item["group"] else ""
            lines.append(f"- {label}订单数 {item['order_count']}，指标值 {item['metric_value']}")
        report = "\n".join(lines)
        for title in ("时间范围：", "指标：", "口径：", "数据来源："):
            if title not in report:
                return _incomplete(["报表模板"], "模板四项没有写全，报表不能当作完成")
        return {
            "complete": True,
            "missing": [],
            "time_range": f"{date_from} 至 {date_to}",
            "metric": metric,
            "definition": definition,
            "source": _SOURCE,
            "numbers": numbers,
            "report": report,
        }

    sales_report.__name__ = "sales_report"
    return sales_report
