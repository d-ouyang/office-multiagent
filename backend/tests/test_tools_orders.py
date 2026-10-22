"""query_orders：参数白名单、行数上限、不返回个人联系方式。"""
import csv
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.orchestration.orders_seed import COLUMNS, ensure_orders_loaded
from app.orchestration.tools_orders import make_query_orders_tool


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    cols = ", ".join(f"{name} TEXT" for name in COLUMNS)
    with eng.begin() as conn:
        conn.execute(text(f"CREATE TABLE guoquan_orders ({cols})"))
        conn.execute(
            text(
                "INSERT INTO guoquan_orders "
                "(order_no, order_create_time, order_status, order_channel, store_name, store_address, "
                "pay_amount, goods_list, user_phone, receiver_phone, user_name) VALUES "
                "('GQ1','2025-01-02 17:43:52','已完成','微信小程序','锅圈食汇(天山店)','上海市长宁区天山路1号','10.50','毛肚x1','13800000000','13900000000','王芳'),"
                "('GQ2','2025-06-01 12:00:00','已取消','美团外卖','锅圈食汇(迎江店)','安庆市迎江区华中路1号','0','烤肠x1','13700000000','','李四'),"
                "('GQ3','2025-01-20 09:00:00','已完成','微信小程序','锅圈食汇(大场店)','上海市宝山区大场镇1号','20','虾滑x2','13600000000','','赵六')"
            )
        )
    return eng


def test_requires_a_filter(engine):
    out = make_query_orders_tool(engine)()
    assert "必须带" in out["error"]


def test_rejects_unknown_status(engine):
    out = make_query_orders_tool(engine)(order_status="已发货")
    assert "没有这个订单状态" in out["error"]


def test_filters_city_and_hides_phones(engine):
    out = make_query_orders_tool(engine)(city="上海", date_from="2025-01-01", date_to="2025-01-31")
    assert out["total_matched"] == 2
    assert {row["order_no"] for row in out["rows"]} == {"GQ1", "GQ3"}
    assert "user_phone" not in out["rows"][0]
    assert "13800000000" not in str(out["rows"])
    assert "王芳" not in str(out["rows"])


def test_groups_pay_by_city(engine):
    out = make_query_orders_tool(engine)(group_by="city", metric="sum_pay", date_from="2025-01-01", date_to="2025-12-31")
    by_city = {row["grp"]: float(row["metric_value"]) for row in out["rows"]}
    assert by_city["上海"] == pytest.approx(30.5)
    assert by_city["安庆"] == pytest.approx(0)


def test_order_detail_includes_goods_not_phone(engine):
    out = make_query_orders_tool(engine)(order_no="GQ1")
    assert out["row_count"] == 1
    assert out["rows"][0]["goods_list"] == "毛肚x1"
    assert "user_phone" not in out["rows"][0]


def test_limit_marks_truncated(engine):
    out = make_query_orders_tool(engine)(city="上海", limit=1)
    assert out["row_count"] == 1
    assert out["truncated"] is True
    assert out["total_matched"] == 2


def test_loads_csv_once(tmp_path: Path):
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    cols = ", ".join(f"{name} TEXT" for name in COLUMNS)
    with eng.begin() as conn:
        conn.execute(text(f"CREATE TABLE guoquan_orders ({cols})"))
    path = tmp_path / "orders.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS))
        writer.writeheader()
        row = {name: "" for name in COLUMNS}
        row.update(
            order_no="GQ9",
            order_create_time="2026-01-01 10:00:00",
            order_status="已完成",
            pay_amount="1.00",
            goods_quantity="1",
            user_phone="13100000000",
        )
        writer.writerow(row)
    assert ensure_orders_loaded(eng, path) == "loaded 1"
    assert ensure_orders_loaded(eng, path) == "ready 1"
    out = make_query_orders_tool(eng)(order_no="GQ9")
    assert out["rows"][0]["order_no"] == "GQ9"
    assert "13100000000" not in str(out["rows"])
