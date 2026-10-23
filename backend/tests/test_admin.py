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
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
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
