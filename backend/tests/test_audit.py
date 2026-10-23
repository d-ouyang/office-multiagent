"""审计日志（p6.28a）+ 管理端独立登录 + 列表分页（p6.28b）。"""
import bcrypt
import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core import audit_repo
from app.core.config import settings
from app.main import app

SECRET = "test-secret-audit"


@pytest.fixture
def eng(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as c:
        c.execute(text("CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0, password_hash TEXT)"))
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', note TEXT, amount INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(
            text(
                "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id INTEGER, "
                "actor_username TEXT NOT NULL, actor_role TEXT, action TEXT NOT NULL, target_type TEXT NOT NULL, "
                "target_id TEXT, target_label TEXT, detail TEXT, ip TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role, password_hash) VALUES (1, 'EMP001', 'dev', 'admin', :h)"),
                  {"h": bcrypt.hashpw(b"Office@2026", bcrypt.gensalt()).decode()})
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role, password_hash) VALUES (2, 'EMP002', 'chen', 'user', :h)"),
                  {"h": bcrypt.hashpw(b"Office@2026", bcrypt.gensalt()).decode()})
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, 100000), (2, 100)"))
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo", "app.core.audit_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)
    return engine


def _auth(emp: str = "EMP001") -> dict[str, str]:
    token = pyjwt.encode({"sub": emp, "tv": 0}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# 仓储层：只写只读 / 白名单 / 敏感拦截
# --------------------------------------------------------------------------- #

def test_record_and_list(eng):
    audit_repo.record(
        actor_user_id=1, actor_username="dev", actor_role="admin",
        action="admin.recharge", target_type="user", target_id=2,
        target_label="chen", detail={"amount": 5000, "balance_after": 5100},
    )
    rows, total = audit_repo.list_logs()
    assert total == 1
    row = rows[0]
    assert row["action"] == "admin.recharge"
    assert row["action_label"] == "给用户充值"
    assert row["detail"] == {"amount": 5000, "balance_after": 5100}  # JSON 已解析
    assert row["actor_username"] == "dev"


def test_unknown_action_rejected(eng):
    with pytest.raises(audit_repo.AuditRefused):
        audit_repo.record(
            actor_user_id=1, actor_username="dev", actor_role="admin",
            action="admin.typo.action", target_type="user",
        )


@pytest.mark.parametrize("detail", [
    {"new_password": "x"},
    {"user": {"password_hash": "$2b$12$..."}},
    {"note": "hash is $2a$10$abcdef"},
])
def test_sensitive_detail_rejected(eng, detail):
    with pytest.raises(audit_repo.AuditRefused):
        audit_repo.record(
            actor_user_id=1, actor_username="dev", actor_role="admin",
            action="admin.recharge", target_type="user", detail=detail,
        )


def test_list_filters(eng):
    audit_repo.record(actor_user_id=1, actor_username="dev", actor_role="admin",
                      action="admin.recharge", target_type="user", target_label="chen")
    audit_repo.record(actor_user_id=1, actor_username="dev", actor_role="admin",
                      action="admin.pool.create", target_type="pool", target_label="finance")
    rows, total = audit_repo.list_logs(action="admin.pool.create")
    assert total == 1 and rows[0]["target_label"] == "finance"
    rows, total = audit_repo.list_logs(target_type="user")
    assert total == 1
    rows, total = audit_repo.list_logs(keyword="fin")
    assert total == 1 and rows[0]["action"] == "admin.pool.create"


def test_no_update_or_delete_api():
    """结构性约束：仓储层不提供 update / delete（照搬 RAG 的三道约束之一）。"""
    assert not hasattr(audit_repo, "update")
    assert not hasattr(audit_repo, "delete")


# --------------------------------------------------------------------------- #
# 管理端独立登录（p6.28a）
# --------------------------------------------------------------------------- #

def test_admin_login_success_and_audit(eng):
    c = TestClient(app)
    r = c.post("/api/v1/admin/login", json={"username": "dev", "password": "Office@2026"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "admin"
    payload = pyjwt.decode(body["access_token"], SECRET, algorithms=["HS256"])
    assert payload["sub"] == "EMP001" and payload["tv"] == 0
    rows, total = audit_repo.list_logs(action="admin.login.success")
    assert total == 1 and rows[0]["actor_username"] == "dev"


def test_admin_login_wrong_password_audits_failure(eng):
    c = TestClient(app)
    r = c.post("/api/v1/admin/login", json={"username": "dev", "password": "wrong"})
    assert r.status_code == 401
    rows, total = audit_repo.list_logs(action="admin.login.failure")
    assert total == 1 and rows[0]["detail"]["reason"] == "bad_credentials"


def test_admin_login_non_admin_rejected(eng):
    c = TestClient(app)
    r = c.post("/api/v1/admin/login", json={"username": "chen", "password": "Office@2026"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "FORBIDDEN"
    rows, _ = audit_repo.list_logs(action="admin.login.failure")
    assert rows and rows[0]["detail"]["admin"] is False


def test_admin_password_change_rotates_token(eng):
    c = TestClient(app)
    login = c.post("/api/v1/admin/login", json={"username": "dev", "password": "Office@2026"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    r = c.post(
        "/api/v1/admin/password",
        json={"old_password": "Office@2026", "new_password": "NewPass123"},
        headers=headers,
    )
    assert r.status_code == 200
    # 新 token 的 tv=1；旧 token 失效
    new_payload = pyjwt.decode(r.json()["access_token"], SECRET, algorithms=["HS256"])
    assert new_payload["tv"] == 1
    assert c.get("/api/v1/admin/users", headers=headers).status_code == 401
    rows, total = audit_repo.list_logs(action="admin.password.change")
    assert total == 1


def test_admin_password_change_rejects_weak(eng):
    c = TestClient(app)
    login = c.post("/api/v1/admin/login", json={"username": "dev", "password": "Office@2026"}).json()
    r = c.post(
        "/api/v1/admin/password",
        json={"old_password": "Office@2026", "new_password": "123"},
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# 审计接口 + 分页
# --------------------------------------------------------------------------- #

def test_audit_logs_endpoint_filters_and_pagination(eng):
    for i in range(25):
        audit_repo.record(
            actor_user_id=1, actor_username="dev", actor_role="admin",
            action="admin.recharge" if i % 2 else "admin.pool.create",
            target_type="user" if i % 2 else "pool", target_label=f"t{i}",
        )
    c = TestClient(app)
    r = c.get("/api/v1/admin/audit-logs", params={"page": 1, "page_size": 10}, headers=_auth())
    body = r.json()
    assert body["total"] == 25 and len(body["logs"]) == 10
    assert {a["value"] for a in body["actions"]} >= {"admin.recharge", "admin.pool.create"}
    page2 = c.get("/api/v1/admin/audit-logs", params={"page": 3, "page_size": 10}, headers=_auth()).json()
    assert len(page2["logs"]) == 5
    filtered = c.get("/api/v1/admin/audit-logs", params={"action": "admin.recharge"}, headers=_auth()).json()
    assert filtered["total"] == 12  # 0~24 中奇数 12 个


def test_audit_logs_requires_admin(eng):
    c = TestClient(app)
    assert c.get("/api/v1/admin/audit-logs", headers=_auth("EMP002")).status_code == 403


def test_recharge_writes_audit(eng):
    c = TestClient(app)
    r = c.post("/api/v1/admin/users/2/recharge", json={"amount": 3000, "note": "测试"}, headers=_auth())
    assert r.status_code == 200
    rows, total = audit_repo.list_logs(action="admin.recharge")
    assert total == 1
    assert rows[0]["detail"]["amount"] == 3000
    assert rows[0]["target_id"] == "2"


def test_users_and_tasks_pagination(eng):
    for i in range(7):
        with eng.begin() as conn:
            conn.execute(
                text("INSERT INTO `user` (id, employee_id, username, role) VALUES (:i, :e, :u, 'user')"),
                {"i": 100 + i, "e": f"E{i}", "u": f"u{i}"},
            )
            conn.execute(
                text("INSERT INTO session (id, user_id) VALUES (:s, 1)"), {"s": f"s{i}"}
            )
            conn.execute(
                text("INSERT INTO task (id, session_id, status, text) VALUES (:t, :s, 'done', 'x')"),
                {"t": f"t{i}", "s": f"s{i}"},
            )
    c = TestClient(app)
    page1 = c.get("/api/v1/admin/users", params={"page": 1, "page_size": 5}, headers=_auth()).json()
    assert page1["total"] == 9 and len(page1["users"]) == 5
    page2 = c.get("/api/v1/admin/users", params={"page": 2, "page_size": 5}, headers=_auth()).json()
    assert len(page2["users"]) == 4
    tasks = c.get("/api/v1/admin/tasks", params={"page": 2, "page_size": 5}, headers=_auth()).json()
    assert tasks["total"] == 7 and len(tasks["tasks"]) == 2
