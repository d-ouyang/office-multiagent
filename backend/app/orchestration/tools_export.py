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
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .orders_seed import COLUMNS, COLUMN_LABELS as _COLUMN_LABELS, ensure_orders_loaded
from .tools_db import _jsonable
from .tools_orders import (
    _CUSTOMER_PII,
    _PHONE_COLUMNS,
    compile_order_filters,
    derive_city,
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
    return derive_city(store_address)


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
    "支付时间": ("支付时间", _col("pay_time")),
    "门店地址": ("门店地址", _col("store_address")),
    "门店编号": ("门店编号", _col("store_id")),
    "门店电话": ("门店电话", _col("store_phone")),
    "营业时间": ("营业时间", _col("store_business_hours")),
    "商品清单": ("商品清单", _col("goods_list")),
    "商品明细": ("商品清单", _col("goods_list")),
    "商品金额": ("商品金额", _col("goods_amount")),
    "配送费": ("配送费", _col("delivery_fee")),
    "包装费": ("包装费", _col("packing_fee")),
    "活动名称": ("活动名称", _col("activity_name")),
    "活动编号": ("活动编号", _col("activity_id")),
    "备注": ("备注", _col("order_remark")),
    "完成时间": ("完成时间", _col("order_complete_time")),
    "获得积分": ("获得积分", _col("points_earned")),
    "会员积分": ("会员积分", _col("member_points")),
    "是否用券": ("是否用券", _col("is_coupon_used")),
    "券名称": ("券名称", _col("coupon_name")),
    "券类型": ("券类型", _col("coupon_type")),
    "券面额": ("券面额", _col("coupon_value")),
    "券码": ("券码", _col("coupon_code")),
    "用户昵称": ("用户昵称", _col("user_nickname")),
    "性别": ("性别", _col("user_gender")),
    "是否要发票": ("是否要发票", _col("need_invoice")),
    "用户编号": ("用户编号", _col("user_id")),
    # 表里确实没有的字段：省略而非报错
    "支付方式": ("", _NONE),
    "付款方式": ("", _NONE),
}

_PII_OMIT = object()
_PII_ALIAS = frozenset({"收货人", "姓名", "真实姓名", "收货地址", "用户姓名"})
# SELECT 用。手机号只参与脱敏，姓名和收货地址不取出。
_DB_COLUMNS = tuple(name for name in COLUMNS if name not in _CUSTOMER_PII or name in _PHONE_COLUMNS)


def _resolve_field(name: str) -> tuple[str, Any] | None:
    """中文别名、派生列，或订单表真实列名。认不出返回 None。"""
    if name in _PII_ALIAS:
        return ("", _PII_OMIT)
    spec = _FIELD_SPECS.get(name)
    if spec is not None:
        return spec
    if name in _PHONE_COLUMNS:
        return ("用户(脱敏)", lambda row, column=name: _mask_phone(row.get(column)))
    if name in _CUSTOMER_PII:
        return ("", _PII_OMIT)
    if name in COLUMNS:
        return (_COLUMN_LABELS.get(name, name), _col(name))
    return None


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
        order_status: str | list[str] | None = None,
        exclude_status: str | list[str] | None = None,
        order_channel: str | list[str] | None = None,
        order_type: str | list[str] | None = None,
        fulfillment_type: str | list[str] | None = None,
        member_level: str | list[str] | None = None,
        fields: list[str] | str | None = None,
        filters: list[dict[str, Any]] | dict[str, Any] | None = None,
        format: str = "csv",
    ) -> dict[str, Any]:
        if engine is None:
            return {"error": "数据库不可用：未配置数据库连接"}
        loaded = ensure_orders_loaded(engine)
        if loaded == "missing":
            return {"error": "订单表还没有建立"}
        if loaded == "empty-no-csv":
            return {"error": "订单表是空的，且没有可导入的 CSV"}

        built = compile_order_filters(
            {
                "date_from": date_from,
                "date_to": date_to,
                "city": city,
                "store_name": store_name,
                "order_status": order_status,
                "exclude_status": exclude_status,
                "order_channel": order_channel,
                "order_type": order_type,
                "fulfillment_type": fulfillment_type,
                "member_level": member_level,
                "filters": filters,
            },
            require_dates=True,
        )
        if built.get("error"):
            return built
        fmt = (format or "csv").strip().lower()
        if fmt == "excel":
            fmt = "xlsx"
        if fmt not in ("csv", "xlsx"):
            return {"error": "format 只支持 csv 或 xlsx"}

        # 字段解析：中文别名、派生列，或订单表列名。没有的列省略并说明。
        requested = [f.strip() for f in (fields if isinstance(fields, list) else ([fields] if fields else [])) if str(f).strip()]
        requested = requested or list(_DEFAULT_FIELDS)
        columns: list[tuple[str, Callable[[dict[str, Any]], str]]] = []
        omitted: dict[str, str] = {}
        seen: set[str] = set()
        for name in requested:
            spec = _resolve_field(name)
            if spec is None:
                omitted[name] = "没有这个字段（可用中文列名或订单表列名；见返回的 available_fields）"
                continue
            col_name, getter = spec
            if col_name and col_name in seen:
                continue
            if getter is _NONE:
                omitted[name] = "订单表没有此字段，按约定整列省略"
                continue
            if getter is _PII_OMIT:
                omitted[name] = "真实姓名和收货地址不导出"
                continue
            seen.add(col_name)
            columns.append((col_name, getter))
        if not columns:
            return {
                "error": "请求的字段全部无法生成",
                "available_fields": sorted(
                    {k for k, v in _FIELD_SPECS.items() if v[1] is not _NONE}
                    | {name for name in COLUMNS if name not in _CUSTOMER_PII or name in _PHONE_COLUMNS}
                ),
            }

        cap = min(max_rows, _MAX_EXPORT_ROWS)
        params = dict(built["params"])
        params["cap"] = cap + 1
        where = " AND ".join(built["clauses"])
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
            return {
                "error": f"该筛选范围内没有订单（{built['applied'].get('date_from')} ~ {built['applied'].get('date_to')}）",
                "filters": built["applied"],
            }

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
            "filters": built["applied"],
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
