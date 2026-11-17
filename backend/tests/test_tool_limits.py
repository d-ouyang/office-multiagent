"""工具结果截断契约测试（v2.4.1）。

背景：真跑"城市×月份热力图"时结果 truncated——根因是 `db_query_max_rows=50`
同时管"明细行"和"分组组数"。分组行数 = 维度组合数（20 城 × 2 月 = 40、34 门店 × 2 月 = 68），
用明细上限去卡必然缺组。修法：两者分开 + 截断必须可感知（truncated_hint）。
"""
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.orchestration.tools_db import make_db_query_tool
from app.orchestration.tools_table import _MAX_GROUPS


def test_aggregate_cap_is_much_larger_than_detail_cap():
    """T-1：聚合组数上限必须显著高于明细行上限（差一个数量级）。"""
    assert settings.aggregate_max_groups >= settings.db_query_max_rows * 5


def test_analyze_table_group_cap_matches_config():
    """T-2：analyze_table 的分组上限与配置一致，避免两处各说各话。"""
    assert _MAX_GROUPS == settings.aggregate_max_groups


def test_db_query_reports_truncation_with_hint():
    """T-3：db_query 不再静默截断——行数打满时给出 truncated + 可执行提示。"""
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE t (id INTEGER)"))
        for i in range(5):
            c.execute(text("INSERT INTO t (id) VALUES (:i)"), {"i": i})
    tool = make_db_query_tool(eng, max_rows=2)
    r = tool("SELECT id FROM t WHERE id >= 0 ORDER BY id")
    assert r["row_count"] == 2
    assert r["truncated"] is True
    assert "上限 2" in (r["truncated_hint"] or "")


def test_db_query_no_hint_when_under_cap():
    """T-4：没截断时不要乱提示（否则模型会以为数据不全）。"""
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE t (id INTEGER)"))
        c.execute(text("INSERT INTO t (id) VALUES (1)"))
    r = make_db_query_tool(eng, max_rows=50)("SELECT id FROM t WHERE id >= 0")
    assert r["truncated"] is False
    assert r["truncated_hint"] is None
