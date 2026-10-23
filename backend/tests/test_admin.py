"""管理端最小版（p7.1）：用户列表 + 充值 + 账本；role 校验 fail-closed。"""
import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.main import app


@pytest.fixture
def eng(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as c:
        c.execute(text("CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', note TEXT, amount INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        # p6.26：概览/任务监控要查 task 与 session
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (1, 'EMP001', 'dev', 'admin')"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (2, 'EMP002', 'chen', 'user')"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, 100000)"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (2, 500)"))
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-admin")
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)
    return engine


def _auth(emp: str = "EMP001") -> dict[str, str]:
    token = pyjwt.encode({"sub": emp, "tv": 0}, "test-secret-admin", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_users_list_requires_admin(eng):
    c = TestClient(app)
    r = c.get("/api/v1/admin/users", headers=_auth("EMP002"))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "FORBIDDEN"


def test_users_list_includes_balance_and_search(eng):
    c = TestClient(app)
    r = c.get("/api/v1/admin/users", headers=_auth())
    assert r.status_code == 200
    users = {u["username"]: u for u in r.json()["users"]}
    assert users["dev"]["balance"] == 100000
    assert users["chen"]["balance"] == 500
    found = c.get("/api/v1/admin/users", params={"q": "chen"}, headers=_auth()).json()["users"]
    assert [u["username"] for u in found] == ["chen"]


def test_recharge_updates_balance_and_ledger(eng):
    c = TestClient(app)
    r = c.post(
        "/api/v1/admin/users/2/recharge",
        json={"amount": 5000, "note": "月度补充"},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["balance"] == 5500
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT kind, note, reserve, settle FROM token_ledger WHERE user_id=2 ORDER BY id DESC LIMIT 1")
        ).mappings().first()
    assert row["kind"] == "recharge"
    assert row["reserve"] is None and row["settle"] is None
    assert "月度补充" in row["note"] and "操作人 1" in row["note"]
    # 用户自己 /quota 能看到充值流水（kind 字段）
    quota = c.get("/api/v1/quota", headers=_auth("EMP002")).json()
    assert any(item["kind"] == "recharge" for item in quota["ledger"])


def test_recharge_creates_wallet_when_missing(eng):
    with eng.begin() as c:
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (3, 'EMP003', 'zhao', 'user')"))
    resp = TestClient(app).post(
        "/api/v1/admin/users/3/recharge", json={"amount": 800}, headers=_auth()
    )
    assert resp.status_code == 200 and resp.json()["balance"] == 800


@pytest.mark.parametrize("amount", [0, -5, 10_000_001])
def test_recharge_rejects_bad_amount(eng, amount):
    r = TestClient(app).post(
        "/api/v1/admin/users/2/recharge", json={"amount": amount}, headers=_auth()
    )
    assert r.status_code == 400


def test_recharge_unknown_user_404(eng):
    r = TestClient(app).post(
        "/api/v1/admin/users/999/recharge", json={"amount": 100}, headers=_auth()
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "USER_NOT_FOUND"


def test_ledger_requires_admin_and_returns_rows(eng):
    c = TestClient(app)
    assert c.get("/api/v1/admin/users/2/ledger", headers=_auth("EMP002")).status_code == 403
    c.post("/api/v1/admin/users/2/recharge", json={"amount": 300}, headers=_auth())
    r = c.get("/api/v1/admin/users/2/ledger", headers=_auth())
    assert r.status_code == 200
    assert r.json()["ledger"][0]["kind"] == "recharge"


def test_admin_endpoints_require_login(eng):
    c = TestClient(app)
    assert c.get("/api/v1/admin/users").status_code == 401
    assert c.post("/api/v1/admin/users/2/recharge", json={"amount": 1}).status_code == 401


# --------------------------------------------------------------------------- #
# p6.26：概览 / 用量 / 任务监控
# --------------------------------------------------------------------------- #

def test_overview_counts_and_zero_safe(eng):
    c = TestClient(app)
    data = c.get("/api/v1/admin/overview", headers=_auth()).json()
    assert data["users_total"] == 2
    assert data["balance_total"] == 100500  # 100000 + 500
    assert data["tasks_total"] == 0 and data["month_tokens"] == 0

    c.post("/api/v1/admin/users/2/recharge", json={"amount": 3000}, headers=_auth())
    data2 = c.get("/api/v1/admin/overview", headers=_auth()).json()
    assert data2["recharge_total"] == 3000  # 只统计有金额的充值
    assert data2["recharge_count"] == 1
    assert data2["balance_total"] == 103500


def test_overview_month_tokens_only_task_settles(eng):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, kind, reserve, settle) VALUES (1, 't1', 'task', 2000, 1500)"))
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, kind, reserve, settle) VALUES (1, 't2', 'task', 2000, NULL)"))
        conn.execute(text("INSERT INTO token_ledger (user_id, kind, amount) VALUES (1, 'recharge', 9999)"))
    data = TestClient(app).get("/api/v1/admin/overview", headers=_auth()).json()
    assert data["month_tokens"] == 1500  # 只计 settle 行；预扣行/充值行不算
    assert data["month_calls"] == 1


def test_usage_series_by_day(eng):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, kind, reserve, settle, created_at) VALUES (1, 'a', 'task', 2000, 100, '2026-10-21 10:00:00')"))
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, kind, reserve, settle, created_at) VALUES (1, 'b', 'task', 2000, 200, '2026-10-21 11:00:00')"))
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, kind, reserve, settle, created_at) VALUES (2, 'c', 'task', 2000, 300, '2026-10-22 12:00:00')"))
    data = TestClient(app).get("/api/v1/admin/usage?days=30", headers=_auth()).json()
    series = {row["date"]: row for row in data["series"]}
    assert series["2026-10-21"]["tokens"] == 300 and series["2026-10-21"]["calls"] == 2
    assert series["2026-10-22"]["tokens"] == 300


def test_admin_tasks_global_with_username_and_filter(eng):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO session (id, user_id) VALUES ('s1', 1)"))
        conn.execute(text("INSERT INTO session (id, user_id) VALUES ('s2', 2)"))
        conn.execute(
            text("INSERT INTO task (id, session_id, status, text, tokens_used, pause_reason) VALUES ('t-a', 's1', 'done', '查年假', 120, NULL)")
        )
        conn.execute(
            text("INSERT INTO task (id, session_id, status, text, tokens_used, pause_reason) VALUES ('t-b', 's2', 'paused_user', '清洗表格', 0, 'user')")
        )
    c = TestClient(app)
    rows = c.get("/api/v1/admin/tasks", headers=_auth()).json()["tasks"]
    assert {r["id"] for r in rows} == {"t-a", "t-b"}
    by_id = {r["id"]: r for r in rows}
    assert by_id["t-a"]["username"] == "dev"
    assert by_id["t-b"]["username"] == "chen" and by_id["t-b"]["pause_reason"] == "user"
    paused = c.get("/api/v1/admin/tasks?status=paused_user", headers=_auth()).json()["tasks"]
    assert [r["id"] for r in paused] == ["t-b"]


def test_admin_tasks_requires_admin(eng):
    assert TestClient(app).get("/api/v1/admin/tasks", headers=_auth("EMP002")).status_code == 403
