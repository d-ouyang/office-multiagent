"""compare_orders：环比、同比、占比都由查询结果计算。"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.orchestration.orders_seed import COLUMNS
from app.orchestration.tools_compare import make_compare_orders_tool


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    cols = ", ".join(f"{name} TEXT" for name in COLUMNS)
    with eng.begin() as conn:
        conn.execute(text(f"CREATE TABLE guoquan_orders ({cols})"))
        conn.execute(text(
            "INSERT INTO guoquan_orders (order_no, order_create_time, order_channel, pay_amount) VALUES "
            "('A','2026-01-10 10:00:00','微信小程序','100'),"
            "('B','2026-02-10 10:00:00','微信小程序','50'),"
            "('C','2026-02-11 10:00:00','美团外卖','50'),"
            "('D','2025-02-10 10:00:00','微信小程序','40')"
        ))
    return eng


def test_month_over_month_and_share(engine):
    tool = make_compare_orders_tool(engine)
    mom = tool(date_from="2026-02-01", date_to="2026-02-28", metric="sum_pay", mode="mom")
    assert mom["rows"][0]["current"] == pytest.approx(100)
    assert mom["rows"][0]["previous"] == pytest.approx(100)
    assert mom["rows"][0]["ratio"] == pytest.approx(0)
    share = tool(
        date_from="2026-02-01", date_to="2026-02-28", metric="sum_pay", mode="share", group_by="order_channel",
    )
    by = {row["group"]: row["share"] for row in share["rows"]}
    assert by["微信小程序"] == pytest.approx(0.5)
    assert by["美团外卖"] == pytest.approx(0.5)
    assert "必须带" in tool(date_from="2026-02-01", date_to="2026-02-28", mode="share")["error"]


def test_year_over_year(engine):
    out = make_compare_orders_tool(engine)(
        date_from="2026-02-01", date_to="2026-02-28", metric="sum_pay", mode="yoy",
    )
    row = out["rows"][0]
    assert row["current"] == pytest.approx(100)
    assert row["previous"] == pytest.approx(40)
    assert row["ratio"] == pytest.approx(1.5)
