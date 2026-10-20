"""会话 API + 身份解析测试（p6.2c）——sqlite 内存库 + 自签 JWT，不连真库不花钱。"""
import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.config import settings
from app.core.session_repo import SessionRepo

SECRET = "test-jwt-secret-p62c"


@pytest.fixture
def engine():
    # check_same_thread=False：FastAPI 同步 handler 在线程池跑，StaticPool 单连接要允许跨线程
    eng = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with eng.begin() as c:
        c.execute(text("CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT UNIQUE, username TEXT, password_hash TEXT, role TEXT, model_pool_id INTEGER, created_at TEXT)"))
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role, model_pool_id) VALUES (1,'EMP001','dev','admin',3)"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, 100000)"))
    return eng


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    # 所有 get_engine() 指向内存库（repo/identity 都走它）
    monkeypatch.setattr("app.core.db.get_engine", lambda: engine)
    monkeypatch.setattr("app.core.identity.get_engine", lambda: engine)
    monkeypatch.setattr("app.core.session_repo.get_engine", lambda: engine)
    return TestClient(app)


def _token(employee_id: str = "EMP001", secret: str = SECRET) -> str:
    return pyjwt.encode({"sub": employee_id, "username": "dev", "role": "admin"}, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------- 身份解析 ----------
def test_resolve_user_ok(engine, monkeypatch):
    from app.core.identity import resolve_user

    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr("app.core.identity.get_engine", lambda: engine)
    u = resolve_user(f"Bearer {_token()}")
    assert u is not None and u["employee_id"] == "EMP001" and u["id"] == 1


def test_resolve_user_rejects_bad_token(engine, monkeypatch):
    from app.core.identity import resolve_user

    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr("app.core.identity.get_engine", lambda: engine)
    assert resolve_user(f"Bearer {_token(secret='wrong')}") is None
    assert resolve_user(None) is None
    assert resolve_user("Basic xyz") is None
    assert resolve_user(f"Bearer {_token(employee_id='EMP999')}") is None  # 查无此人


def test_resolve_user_no_secret_fails_closed(engine, monkeypatch):
    from app.core.identity import resolve_user

    # token 是合法签的，但服务端 secret 未配置 → fail-closed（不拿请求里的密钥兜底）
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr("app.core.identity.get_engine", lambda: engine)
    assert resolve_user(f"Bearer {_token(secret='attacker-known')}") is None


# ---------- sessions REST ----------
def test_sessions_crud_flow(client):
    r = client.post("/api/v1/sessions", json={}, headers=_auth(_token()))
    assert r.status_code == 200
    sid = r.json()["session_id"]

    r = client.get("/api/v1/sessions", headers=_auth(_token()))
    assert r.status_code == 200
    assert any(s["session_id"] == sid for s in r.json()["sessions"])
    assert r.json()["sessions"][0]["title"] == "新会话"

    r = client.get(f"/api/v1/sessions/{sid}/messages", headers=_auth(_token()))
    assert r.status_code == 200 and r.json()["messages"] == []


def test_sessions_requires_token(client):
    assert client.post("/api/v1/sessions", json={}).status_code == 401
    assert client.get("/api/v1/sessions").status_code == 401


def test_session_messages_cross_user_404(client):
    # 别人的会话（user id=2）dev 读不到：归属校验 fail-closed
    from app.core.db import get_engine
    from app.core.session_repo import SessionRepo

    other_sid = SessionRepo(get_engine()).create_session(2)
    r = client.get(f"/api/v1/sessions/{other_sid}/messages", headers=_auth(_token()))
    assert r.status_code == 404


def test_quota_endpoint(client):
    # p6.4：/quota 返回余额与流水（种子 100000，暂无流水）
    r = client.get("/api/v1/quota", headers=_auth(_token()))
    assert r.status_code == 200
    assert r.json()["balance"] == 100000
    assert r.json()["ledger"] == []


def test_quota_requires_token(client):
    assert client.get("/api/v1/quota").status_code == 401
