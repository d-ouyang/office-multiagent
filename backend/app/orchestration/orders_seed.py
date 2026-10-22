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
