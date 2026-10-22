"""db_query 只读护栏测试（p5.1a）——护栏全部 fail-closed，逐条断言。"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.orchestration.tools_db import check_readonly, make_db_query_tool


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, created_at TEXT)"))
        c.execute(
            text(
                "INSERT INTO t (id, name, created_at) VALUES "
                "(1,'a','d1'),(2,'b','d2'),(3,'c','d3'),(4,'d','d4'),(5,'e','d5')"
            )
        )
    return eng


# ---------- check_readonly：接受 / 拒绝 ----------
def test_accepts_select():
    assert check_readonly("SELECT * FROM t WHERE id=1").startswith("SELECT")


def test_accepts_cte_select():
    assert "LIMIT" in check_readonly("WITH c AS (SELECT 1 AS x) SELECT * FROM c WHERE x=1")


def test_rejects_write_keywords():
    for bad in (
        "INSERT INTO t VALUES (9,'x','d')",
        "UPDATE t SET name='x'",
        "DELETE FROM t",
        "DROP TABLE t",
        "CREATE TABLE t2 (id INT)",
        "TRUNCATE TABLE t",
    ):
        with pytest.raises(ValueError):
            check_readonly(bad)


def test_no_false_positive_on_column_names():
    # 词边界护栏不误杀 created_at 这类列名
    assert check_readonly("SELECT created_at FROM t WHERE id=1").startswith("SELECT")


def test_rejects_multi_statement():
    with pytest.raises(ValueError, match="分号"):
        check_readonly("SELECT 1; DROP TABLE t")


def test_rejects_non_select():
    with pytest.raises(ValueError, match="SELECT"):
        check_readonly("EXPLAIN SELECT 1")


def test_appends_limit_when_missing():
    assert check_readonly("SELECT * FROM t WHERE id>0", max_rows=7).endswith("LIMIT 7")


def test_keeps_existing_limit():
    out = check_readonly("SELECT * FROM t WHERE id>0 LIMIT 3", max_rows=50)
    assert out.count("LIMIT") == 1


# ---------- db_query 行为 ----------
def test_db_query_returns_rows(engine):
    tool = make_db_query_tool(engine)
    out = tool("SELECT id, name FROM t WHERE id>0 ORDER BY id")
    assert out["columns"] == ["id", "name"]
    assert out["row_count"] == 5
    assert out["rows"][0] == {"id": 1, "name": "a"}
    assert out["rows"][4] == {"id": 5, "name": "e"}


def test_db_query_truncates_to_max_rows(engine):
    tool = make_db_query_tool(engine, max_rows=2)
    out = tool("SELECT * FROM t WHERE id>0 ORDER BY id")
    assert out["row_count"] == 2  # 硬截断


def test_db_query_rejects_write(engine):
    tool = make_db_query_tool(engine)
    with pytest.raises(ValueError):
        tool("DELETE FROM t")


def test_rejects_unbounded_scan():
    with pytest.raises(ValueError, match="WHERE"):
        check_readonly("SELECT * FROM t")


def test_clamps_huge_limit():
    out = check_readonly("SELECT * FROM t WHERE id>0 LIMIT 100000", max_rows=50)
    assert out.endswith("LIMIT 50")
    assert "MAX_EXECUTION_TIME(3000)" in out


def test_db_query_without_engine_is_honest():
    tool = make_db_query_tool(None)
    with pytest.raises(RuntimeError, match="数据库不可用"):
        tool("SELECT 1")
