"""批量补充订单数据（v2.4.1，本地验证用）。

为什么单独一个脚本：`orders_seed.ensure_orders_loaded` 是"空表才灌 CSV"的一次性入口，
不适合往已有库里加数据。这里按现有门店生成合规行，既能丰富 9/10 月之外的分布，
又能让"本月（11 月）"的看板/报表有数据可看。

用法（本地 mysql 未映射宿主端口，所以在 backend 容器里跑）：
    docker exec -i office-multiagent-backend-1 python - < backend/scripts/seed_orders_bulk.py

可调：
    SEED_COUNT=500            总量（默认 500）
    SEED_CURRENT_MONTH=150    其中落在"当月"的条数（默认 150）
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.db import get_engine

COUNT = int(os.environ.get("SEED_COUNT", "500"))
CURRENT_MONTH_COUNT = int(os.environ.get("SEED_CURRENT_MONTH", "150"))
random.seed(20261117)  # 固定种子：可复现，便于反复验证

#: 状态与渠道带权重——真实库里"已完成"占多数，"退款/取消"是长尾
STATUSES = [("已完成", 60), ("已支付", 15), ("配送中", 10), ("待支付", 8), ("已取消", 5), ("已退款", 2)]
CHANNELS = [("美团外卖", 45), ("饿了么外卖", 30), ("门店扫码", 15), ("小程序自提", 10)]
SURNAMES = "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗"
GIVENS = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "洋", "艳", "勇", "军", "杰", "娟", "涛"]
GOODS = ["肥牛卷", "羊肉卷", "虾滑", "毛肚", "鸭肠", "午餐肉", "鱼豆腐", "宽粉", "蘸料套餐", "可乐"]


def _pick(pairs: list[tuple[str, int]]) -> str:
    return random.choices([p[0] for p in pairs], weights=[p[1] for p in pairs], k=1)[0]


def _city_of(address: str) -> str:
    for suffix in ("市", "区", "县"):
        idx = address.find(suffix)
        if idx > 0:
            return address[: idx + 1]
    return address[:4]


def _rand_dt(start: datetime, end: datetime) -> datetime:
    span = max(1, int((end - start).total_seconds()))
    return start + timedelta(seconds=random.randint(0, span))


def _build_row(store: dict, dt: datetime) -> dict:
    goods_qty = random.randint(1, 8)
    goods_amount = round(random.uniform(28, 680), 2)
    delivery_fee = 0.0 if _pick([("自提", 3), ("配送", 7)]) == "自提" else round(random.uniform(2, 6), 2)
    packing_fee = round(random.uniform(0, 3), 2)
    total = round(goods_amount + delivery_fee + packing_fee, 2)
    discount = round(random.uniform(0, 30), 2) if random.random() < 0.45 else 0.0
    pay = round(max(0.01, total - discount), 2)
    status = _pick(STATUSES)
    user_name = random.choice(SURNAMES) + random.choice(GIVENS)
    goods = [{"name": random.choice(GOODS), "qty": random.randint(1, 3)} for _ in range(random.randint(1, 3))]
    return {
        "order_no": f"GQ{dt:%Y%m%d}{random.randint(0, 99999):05d}",
        "order_create_time": dt,
        "pay_time": dt + timedelta(seconds=random.randint(30, 900)),
        "order_status": status,
        "order_type": _pick([("外卖", 7), ("自提", 3)]),
        "order_channel": _pick(CHANNELS),
        "activity_name": _pick([("", 6), ("满减活动", 2), ("新客立减", 2)]),
        "store_id": store["store_id"],
        "store_name": store["store_name"],
        "store_address": store["store_address"],
        "store_business_hours": "09:00-22:00",
        "store_phone": f"1{random.randint(3, 9)}{random.randint(0, 999999999):09d}"[:11],
        "fulfillment_type": _pick([("配送", 6), ("自提", 4)]),
        "goods_list": json.dumps(goods, ensure_ascii=False),
        "goods_quantity": goods_qty,
        "goods_amount": goods_amount,
        "delivery_fee": delivery_fee,
        "packing_fee": packing_fee,
        "total_amount": total,
        "discount_amount": discount,
        "pay_amount": pay,
        "points_earned": int(pay // 10),
        "is_coupon_used": "是" if discount > 0 else "否",
        "coupon_name": "满减券" if discount > 0 else "",
        "coupon_value": discount,
        "receiver_name": user_name,
        "receiver_phone": f"1{random.randint(3, 9)}{random.randint(0, 999999999):09d}"[:11],
        "address": f"{store['store_address']}附近",
        "order_complete_time": dt + timedelta(minutes=random.randint(20, 60)) if status == "已完成" else None,
        "refund_amount": pay if status == "已退款" else 0.0,
        "user_id": f"U{random.randint(1000, 9999)}",
        "user_nickname": user_name,
        "user_name": user_name,
        "user_gender": _pick([("男", 5), ("女", 5)]),
        "member_level": _pick([("普通", 6), ("银卡", 2), ("金卡", 2)]),
        "member_points": random.randint(0, 5000),
        "need_invoice": _pick([("否", 8), ("是", 2)]),
        "order_remark": "",
        "activity_id": "",
        "address_id": "",
    }


def main() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        stores = [
            dict(m) for m in conn.execute(text(
                "SELECT store_id, store_name, store_address FROM guoquan_orders "
                "WHERE store_id IS NOT NULL AND store_id <> '' "
                "GROUP BY store_id, store_name, store_address"
            )).mappings()
        ]
        if not stores:
            print("no stores in guquan_orders — seed the CSV first")
            return

        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        hist_start = datetime(2025, 1, 1)
        hist_end = month_start - timedelta(seconds=1)

        rows: list[dict] = []
        for i in range(COUNT):
            dt = (
                _rand_dt(month_start, now)
                if i < CURRENT_MONTH_COUNT
                else _rand_dt(hist_start, hist_end)
            )
            rows.append(_build_row(random.choice(stores), dt))

        sql = text(
            "INSERT IGNORE INTO guoquan_orders ("
            + ", ".join(rows[0].keys())
            + ") VALUES ("
            + ", ".join(f":{k}" for k in rows[0].keys())
            + ")"
        )
        conn.execute(sql, rows)

    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM guoquan_orders")).scalar()
        by_month = conn.execute(text(
            "SELECT DATE_FORMAT(order_create_time,'%Y-%m') m, COUNT(*) c "
            "FROM guoquan_orders GROUP BY m ORDER BY m DESC LIMIT 6"
        )).all()
        cities = conn.execute(text(
            "SELECT SUBSTRING_INDEX(store_address,'区',1) c, COUNT(*) n "
            "FROM guoquan_orders WHERE order_create_time >= :s "
            "GROUP BY c ORDER BY n DESC LIMIT 5"
        ), {"s": month_start}).all()
    print(f"inserted ~{len(rows)} (INSERT IGNORE 去重后实际可能略少)")
    print("total:", total, "| 最近月份:", [(m, c) for m, c in by_month])
    print("当月城市 TOP5:", [(c, n) for c, n in cities])


if __name__ == "__main__":
    main()
