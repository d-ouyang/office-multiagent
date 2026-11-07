"""把英文表头的订单 CSV 灌进 guoquan_orders。表里已有行就不动。"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

COLUMNS = (
    "order_no",
    "order_create_time",
    "pay_time",
    "order_status",
    "order_type",
    "order_channel",
    "activity_id",
    "activity_name",
    "store_id",
    "store_name",
    "store_address",
    "store_business_hours",
    "store_phone",
    "fulfillment_type",
    "goods_list",
    "goods_quantity",
    "goods_amount",
    "delivery_fee",
    "packing_fee",
    "total_amount",
    "discount_amount",
    "pay_amount",
    "points_earned",
    "is_coupon_used",
    "coupon_code",
    "coupon_type",
    "coupon_name",
    "coupon_value",
    "receiver_name",
    "receiver_phone",
    "address_id",
    "address",
    "order_remark",
    "order_complete_time",
    "refund_amount",
    "user_id",
    "user_nickname",
    "user_name",
    "user_gender",
    "member_level",
    "member_points",
    "user_phone",
    "need_invoice",
)
# 列名 ↔ 中文名标准映射（p5.7 从 tools_export 下沉共享；query_orders/export_orders 通用）
COLUMN_LABELS = {
    "order_no": "订单号",
    "order_create_time": "下单时间",
    "pay_time": "支付时间",
    "order_status": "订单状态",
    "order_type": "订单类型",
    "order_channel": "平台",
    "activity_id": "活动编号",
    "activity_name": "活动名称",
    "store_id": "门店编号",
    "store_name": "门店",
    "store_address": "门店地址",
    "store_business_hours": "营业时间",
    "store_phone": "门店电话",
    "fulfillment_type": "履约方式",
    "goods_list": "商品清单",
    "goods_quantity": "商品件数",
    "goods_amount": "商品金额",
    "delivery_fee": "配送费",
    "packing_fee": "包装费",
    "total_amount": "订单金额",
    "discount_amount": "优惠金额",
    "pay_amount": "销售金额",
    "points_earned": "获得积分",
    "is_coupon_used": "是否用券",
    "coupon_code": "券码",
    "coupon_type": "券类型",
    "coupon_name": "券名称",
    "coupon_value": "券面额",
    "order_remark": "备注",
    "order_complete_time": "完成时间",
    "refund_amount": "退款金额",
    "user_id": "用户编号",
    "user_nickname": "用户昵称",
    "user_gender": "性别",
    "member_level": "会员等级",
    "member_points": "会员积分",
    "need_invoice": "是否要发票",
}

_INT = {"goods_quantity", "points_earned", "member_points"}
_DEC = {
    "goods_amount",
    "delivery_fee",
    "packing_fee",
    "total_amount",
    "discount_amount",
    "pay_amount",
    "coupon_value",
    "refund_amount",
}
_DT = {"order_create_time", "pay_time", "order_complete_time"}


def default_csv_path() -> Path:
    mounted = Path("/app/data/guoquan_orders_2025_2026_en.csv")
    if mounted.exists():
        return mounted
    return Path(__file__).resolve().parents[2] / "data" / "guoquan_orders_2025_2026_en.csv"


def _cell(name: str, raw: str | None) -> Any:
    value = (raw or "").strip()
    if name in _DT:
        return value or None
    if name in _INT:
        return int(value) if value else 0
    if name in _DEC:
        return value or "0"
    return value


def read_order_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in COLUMNS if reader.fieldnames is None or name not in reader.fieldnames]
        if missing:
            raise ValueError(f"订单 CSV 缺少列：{', '.join(missing)}")
        return [{name: _cell(name, row.get(name)) for name in COLUMNS} for row in reader]


def ensure_orders_loaded(engine: Engine, csv_path: Path | None = None) -> str:
    """表不存在时返回 missing；已有数据不覆盖；空表则导入。"""
    path = csv_path or default_csv_path()
    insert_cols = ", ".join(COLUMNS)
    holders = ", ".join(f":{name}" for name in COLUMNS)
    statement = text(f"INSERT INTO guoquan_orders ({insert_cols}) VALUES ({holders})")
    with engine.begin() as conn:
        try:
            count = conn.execute(text("SELECT COUNT(*) FROM guoquan_orders")).scalar()
        except Exception:
            return "missing"
        if count:
            return f"ready {int(count)}"
        if not path.exists():
            return "empty-no-csv"
        rows = read_order_rows(path)
        if rows:
            conn.execute(statement, rows)
        return f"loaded {len(rows)}"
