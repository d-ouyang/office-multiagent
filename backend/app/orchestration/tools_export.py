"""export_orders：订单明细导出（p6.30）——按筛选取明细行，落成 csv/xlsx 文件。

与 query_orders 的分工（两个工具、两份契约，不互相膨胀）：
  · query_orders = 聚合统计（group_by + 指标，≤50 行，LLM 上下文友好，无 PII）；
  · export_orders = 明细交付物（落 _out/ 文件给用户下载/画图，行数上限放宽，
    手机号【脱敏】后进文件，原始号码不出现在任何 LLM 上下文里）。

字段映射规则（用户点单："表格保留我提到的字段，没有的话就跳过"）：
  · 请求字段名 → 列的映射表在 _FIELD_SPECS；表里不存在的字段（如支付方式）
    整列省略并如实列入返回的 omitted（键=字段名，值=原因）；
  · 认不出的字段名同样省略（不报错、不瞎猜列名），在 omitted 里说明；
  · 是否线上 = order_channel 推导：门店扫码→线下，其余渠道→线上（口径写进返回的
    derived_note，对账可查）。
"""
from __future__ import annotations

import csv
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .orders_seed import ensure_orders_loaded
from .tools_db import _jsonable
from .tools_orders import (
    _CHANNELS,
    _CITIES,
    _FULFILLMENT,
    _LEVELS,
    _STATUSES,
    _TYPES,
    _choice,
    _date,
    _text,
)
from .tools_store import finish_output, new_output_id, output_file

_EXPORT_ID = re.compile(r"^e-[0-9a-f]{16}$")
_DEFAULT_FIELDS = ("下单时间", "订单号", "城市", "门店", "用户", "是否线上", "平台", "销售金额", "订单状态")
_MAX_EXPORT_ROWS = 10_000

# 请求字段名（含同义写法）→ (默认列名, 取值函数 or 库列名)
_NONE = object()  # 占位：库中没有这个字段


def _mask_phone(raw: Any) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) >= 11:
        return f"{digits[:3]}****{digits[-4:]}"
    if len(digits) >= 7:
        return f"{digits[:3]}****{digits[-2:]}"
    return ""


def _derive_online(channel: Any) -> str:
    return "线下" if str(channel or "") == "门店扫码" else "线上"


def _derive_city(store_address: Any) -> str:
    addr = str(store_address or "")
    if addr.startswith("上海市"):
        return "上海"
    if addr.startswith("安庆市"):
        return "安庆"
    return "其他"


def _col(name: str) -> Callable[[dict[str, Any]], str]:
    return lambda row: str(row.get(name) if row.get(name) is not None else "")


_FIELD_SPECS: dict[str, tuple[str, Any]] = {
    "下单时间": ("下单时间", _col("order_create_time")),
    "订单号": ("订单号", _col("order_no")),
    "城市": ("城市", lambda row: _derive_city(row.get("store_address"))),
    "门店": ("门店", _col("store_name")),
    "用户": ("用户(脱敏)", lambda row: _mask_phone(row.get("receiver_phone"))),
    "用户信息": ("用户(脱敏)", lambda row: _mask_phone(row.get("receiver_phone"))),
    "手机号": ("用户(脱敏)", lambda row: _mask_phone(row.get("receiver_phone"))),
    "是否线上": ("是否线上", lambda row: _derive_online(row.get("order_channel"))),
    "线上线下": ("是否线上", lambda row: _derive_online(row.get("order_channel"))),
    "平台": ("平台", _col("order_channel")),
    "下单平台": ("平台", _col("order_channel")),
    "渠道": ("平台", _col("order_channel")),
    "销售金额": ("销售金额", _col("pay_amount")),
    "支付金额": ("销售金额", _col("pay_amount")),
    "实付金额": ("销售金额", _col("pay_amount")),
    "订单金额": ("订单金额", _col("total_amount")),
    "优惠金额": ("优惠金额", _col("discount_amount")),
    "退款金额": ("退款金额", _col("refund_amount")),
    "订单状态": ("订单状态", _col("order_status")),
    "订单类型": ("订单类型", _col("order_type")),
    "履约方式": ("履约方式", _col("fulfillment_type")),
    "会员等级": ("会员等级", _col("member_level")),
    "商品件数": ("商品件数", _col("goods_quantity")),
    # 表里确实没有的字段：省略而非报错
    "支付方式": ("", _NONE),
    "付款方式": ("", _NONE),
}

# 库里真实存在的列（SELECT 用；PII 原始值允许进 SELECT，但只用于脱敏/推导，不进返回）
_DB_COLUMNS = (
    "order_no", "order_create_time", "order_status", "order_type", "order_channel",
    "store_name", "store_address", "fulfillment_type", "member_level", "goods_quantity",
    "pay_amount", "total_amount", "discount_amount", "refund_amount", "receiver_phone",
)


def make_export_orders_tool(
    engine: Engine | None,
    *,
    base_dir: str,
    owner: str | None = None,
    user_id: int | None = None,
    task_id: str | None = None,
    max_rows: int = _MAX_EXPORT_ROWS,
) -> Callable[..., Any]:
    del owner  # base_dir 已按用户目录解析
    base = Path(base_dir).resolve()

    def export_orders(
        date_from: str,
        date_to: str,
        city: str | None = None,
        store_name: str | None = None,
        order_status: str | None = None,
        exclude_status: str | None = None,
        order_channel: str | None = None,
        order_type: str | None = None,
        fulfillment_type: str | None = None,
        member_level: str | None = None,
        fields: list[str] | str | None = None,
        format: str = "csv",
    ) -> dict[str, Any]:
        if engine is None:
            return {"error": "数据库不可用：未配置数据库连接"}
        loaded = ensure_orders_loaded(engine)
        if loaded == "missing":
            return {"error": "订单表还没有建立"}
        if loaded == "empty-no-csv":
            return {"error": "订单表是空的，且没有可导入的 CSV"}

        df = _date(date_from, "date_from")
        dt = _date(date_to, "date_to")
        if isinstance(df, dict):
            return df
        if isinstance(dt, dict):
            return dt
        if not df or not dt:
            return {"error": "导出必须带 date_from 和 date_to（明细导出必须有明确时间范围）"}
        if df > dt:
            return {"error": "date_from 不能晚于 date_to"}
        status = _choice(order_status, "订单状态", _STATUSES)
        if isinstance(status, dict):
            return status
        excluded = _choice(exclude_status, "要排除的订单状态", _STATUSES)
        if isinstance(excluded, dict):
            return excluded
        channel = _choice(order_channel, "订单渠道", _CHANNELS)
        if isinstance(channel, dict):
            return channel
        otype = _choice(order_type, "订单类型", _TYPES)
        if isinstance(otype, dict):
            return otype
        fulfillment = _choice(fulfillment_type, "履约方式", _FULFILLMENT)
        if isinstance(fulfillment, dict):
            return fulfillment
        level = _choice(member_level, "会员等级", _LEVELS)
        if isinstance(level, dict):
            return level
        if city and city not in _CITIES:
            return {"error": f"没有这个城市：{city}。可选：上海、安庆"}
        fmt = (format or "csv").strip().lower()
        if fmt == "excel":
            fmt = "xlsx"
        if fmt not in ("csv", "xlsx"):
            return {"error": "format 只支持 csv 或 xlsx"}

        # 字段解析：请求里有就保留（同义名归一），没有/库里没有 → 省略并说明
        requested = [f.strip() for f in (fields if isinstance(fields, list) else ([fields] if fields else [])) if str(f).strip()]
        requested = requested or list(_DEFAULT_FIELDS)
        columns: list[tuple[str, Callable[[dict[str, Any]], str]]] = []
        omitted: dict[str, str] = {}
        seen: set[str] = set()
        for name in requested:
            spec = _FIELD_SPECS.get(name)
            if spec is None:
                omitted[name] = "没有这个字段（可用字段见返回的 available_fields）"
                continue
            col_name, getter = spec
            if col_name and col_name in seen:
                continue
            if getter is _NONE:
                omitted[name] = "订单表没有此字段，按约定整列省略"
                continue
            seen.add(col_name)
            columns.append((col_name, getter))
        if not columns:
            return {
                "error": "请求的字段全部无法生成",
                "available_fields": sorted({k for k, v in _FIELD_SPECS.items() if v[1] is not _NONE}),
            }

        # 查询
        params: dict[str, Any] = {"date_from": f"{df} 00:00:00"}
        year, month, day = (int(p) for p in str(dt).split("-"))
        nxt = datetime(year, month, day) + timedelta(days=1)
        params["date_to_next"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
        filters = ["order_create_time >= :date_from", "order_create_time < :date_to_next"]
        if city:
            filters.append("store_address LIKE :city")
            params["city"] = _CITIES[city]
        if store_name:
            filters.append("store_name LIKE :store_name")
            params["store_name"] = f"%{_text(store_name).replace('%', '').replace('_', '')}%"
        for key, value in (
            ("order_status", status), ("order_channel", channel), ("order_type", otype),
            ("fulfillment_type", fulfillment), ("member_level", level),
        ):
            if value:
                filters.append(f"{key} = :{key}")
                params[key] = value
        if excluded:
            filters.append("order_status <> :exclude_status")
            params["exclude_status"] = excluded
        cap = min(max_rows, _MAX_EXPORT_ROWS)
        params["cap"] = cap + 1
        where = " AND ".join(filters)
        sql = (
            f"SELECT {', '.join(_DB_COLUMNS)} FROM guoquan_orders WHERE {where} "
            f"ORDER BY order_create_time ASC LIMIT :cap"
        )
        with engine.connect() as conn:
            raw_rows = [dict(r) for r in conn.execute(text(sql), params).mappings().all()]
            rows = [
                {k: (_jsonable(row_dict[k]) if row_dict.get(k) is not None else "") for k in _DB_COLUMNS}
                for row_dict in raw_rows
            ]
        truncated = len(rows) > cap
        rows = rows[:cap]
        if not rows:
            return {"error": f"该筛选范围内没有订单（{df} ~ {dt}）", "filters": {"date_from": df, "date_to": dt}}

        headers = [name for name, _ in columns]
        grid = [[getter(row) for _, getter in columns] for row in rows]

        # 落盘
        if base is None:
            return {"error": "导出目录未配置"}
        doc_id = new_output_id("e")
        filename = f"{doc_id}.{fmt}"
        target = output_file(base, filename)
        if fmt == "csv":
            with target.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                writer.writerows(grid)
        else:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.append(headers)
            for row in grid:
                ws.append(row)
            wb.save(str(target))
        rel = f"_out/{filename}"
        recorded = finish_output(
            engine, target,
            asset_id=doc_id, user_id=user_id, task_id=task_id,
            kind=f"export_{fmt}", name=filename, rel_path=rel,
        )
        return {
            "export_id": doc_id,
            "file_name": rel,
            "display_name": filename,
            "format": fmt,
            "row_count": len(grid),
            "columns": headers,
            "omitted": omitted or None,
            "filters": {
                "date_from": df, "date_to": dt,
                **({k: v for k, v in (("city", city), ("store_name", store_name), ("order_status", status),
                                       ("exclude_status", excluded), ("order_channel", channel),
                                       ("order_type", otype), ("fulfillment_type", fulfillment),
                                       ("member_level", level)) if v}),
            },
            "truncated": truncated,
            "recorded": recorded,
            "derived_note": "是否线上=按订单渠道推导：门店扫码→线下，其余渠道→线上。",
            "note": (
                f"已生成明细表 {filename}（{len(grid)} 行）。"
                + ("超过单次导出上限，结果已截断，请缩小时间范围。" if truncated else "")
                + ("缺字段已整列省略：" + "、".join(omitted) if omitted else "")
            ),
        }

    export_orders.__name__ = "export_orders"
    return export_orders


def load_export(base_dir: str, export_id: str) -> tuple[list[str], list[list[str]]]:
    """render_chart 用：按 export_id 读回导出表（headers + 行）。

    csv / xlsx 两种格式都支持（真跑教训：模型可能选 xlsx 导出，只读 csv 会
    "找不到导出表"——run 真机验证抓到）。单元格统一转成字符串，数字保持可解析。
    """
    if not _EXPORT_ID.match(export_id or ""):
        raise ValueError("export_id 无效。请先调用 export_orders，不要把原始文件名传进来。")
    folder = (Path(base_dir) / "_out").resolve()
    csv_path = (folder / f"{export_id}.csv").resolve()
    xlsx_path = (folder / f"{export_id}.xlsx").resolve()
    if not (csv_path.is_relative_to(folder) and xlsx_path.is_relative_to(folder)):
        raise ValueError("export_id 无效")
    if csv_path.is_file():
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            grid = list(csv.reader(handle))
    elif xlsx_path.is_file():
        from openpyxl import load_workbook

        wb = load_workbook(str(xlsx_path), read_only=True, data_only=True)
        ws = wb.active
        grid = [
            [("" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))) for v in row]
            for row in ws.iter_rows(values_only=True)
        ]
        wb.close()
    else:
        raise FileNotFoundError(f"找不到导出表：{export_id}")
    grid = [row for row in grid if any(str(c).strip() for c in row)]
    if len(grid) < 2:
        raise ValueError("导出表没有数据行")
    return grid[0], grid[1:]
