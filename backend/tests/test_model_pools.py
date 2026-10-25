"""模型池配置（p6.27c）：池定义/模型归属/用户分配 + /models 按池过滤。"""
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
        c.execute(text("CREATE TABLE model_pool (id INTEGER PRIMARY KEY, name TEXT)"))
        c.execute(text("CREATE TABLE pool_model (pool_id INTEGER, model_name TEXT, enabled INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (pool_id, model_name))"))
        c.execute(text("INSERT INTO model_pool (id, name) VALUES (1,'default'),(2,'staff'),(3,'admin')"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role, model_pool_id) VALUES (1,'EMP001','dev','admin',3)"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role, model_pool_id) VALUES (2,'EMP002','chen','user',1)"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, 100), (2, 100)"))
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-pool")
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)
    return engine


def _auth(emp: str = "EMP001") -> dict[str, str]:
    token = pyjwt.encode({"sub": emp, "tv": 0}, "test-secret-pool", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_pools_list_with_yaml_default_membership(eng):
    """无 DB 配置时 enabled 回落 yaml 的 pool_ids（池名 ∈ 该模型的 pool_ids）。"""
    c = TestClient(app)
    data = c.get("/api/v1/admin/model-pools", headers=_auth()).json()["pools"]
    names = {p["name"]: p for p in data}
    assert set(names) == {"default", "staff", "admin"}
    admin_models = {m["model_name"]: m["enabled"] for m in names["admin"]["models"]}
    default_models = {m["model_name"]: m["enabled"] for m in names["default"]["models"]}
    # deepseek-reasoner 的 yaml 池是 [staff, admin]：admin 可见、default 不可见
    assert admin_models.get("deepseek-reasoner") is True
    assert default_models.get("deepseek-reasoner") is False
    # deepseek-chat 在三个池都可见
    assert admin_models.get("deepseek-chat") is True
    assert default_models.get("deepseek-chat") is True


def test_models_filters_by_user_pool(eng):
    """dev 在 admin 池（yaml 全量可见）；chen 在 default 池（看不到 staff/admin 专属模型）。"""
    c = TestClient(app)
    dev_ids = {m["id"] for m in c.get("/api/v1/models", headers=_auth("EMP001")).json()["models"]}
    chen_ids = {m["id"] for m in c.get("/api/v1/models", headers=_auth("EMP002")).json()["models"]}
    assert "deepseek-chat" in dev_ids and "deepseek-reasoner" in dev_ids
    assert "deepseek-chat" in chen_ids
    assert "deepseek-reasoner" not in chen_ids  # staff/admin 专属 → default 池不可见


def test_models_all_when_no_token(eng):
    c = TestClient(app)
    all_ids = {m["id"] for m in c.get("/api/v1/models").json()["models"]}
    assert "deepseek-chat" in all_ids      # 未登录不过滤（兼容旧行为）
    assert "deepseek-reasoner" in all_ids


def test_models_all_when_user_has_no_pool(eng):
    """用户 model_pool_id=NULL → 不限制（§十三：未分配=可见全部）。"""
    with eng.begin() as c:
        c.execute(text("UPDATE `user` SET model_pool_id = NULL WHERE id = 1"))
    ids = {m["id"] for m in TestClient(app).get("/api/v1/models", headers=_auth("EMP001")).json()["models"]}
    assert "deepseek-reasoner" in ids


def test_db_override_beats_yaml(eng):
    """DB 显式配置优先：把 deepseek-chat 从 admin 池拿掉，dev 立刻看不到。"""
    c = TestClient(app)
    before = {m["id"] for m in c.get("/api/v1/models", headers=_auth("EMP001")).json()["models"]}
    assert "deepseek-chat" in before
    r = c.put(
        "/api/v1/admin/model-pools/3/models",
        json={"models": [{"model_name": "deepseek-chat", "enabled": False}]},
        headers=_auth(),
    )
    assert r.status_code == 200
    after = {m["id"] for m in c.get("/api/v1/models", headers=_auth("EMP001")).json()["models"]}
    assert "deepseek-chat" not in after
    # 其他模型无 DB 行 → 仍回落 yaml，不受影响
    assert "deepseek-reasoner" in after


def test_db_override_can_add_model(eng):
    """反过来也能把 default 专属模型加进 staff 池（DB 显式开启）。"""
    c = TestClient(app)
    r = c.put(
        "/api/v1/admin/model-pools/2/models",
        json={"models": [{"model_name": "deepseek-chat", "enabled": True}]},
        headers=_auth(),
    )
    assert r.status_code == 200
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT enabled FROM pool_model WHERE pool_id=2 AND model_name='deepseek-chat'")
        ).first()
    assert row is not None and row[0] == 1


def test_put_rejects_unknown_model(eng):
    c = TestClient(app)
    r = c.put(
        "/api/v1/admin/model-pools/3/models",
        json={"models": [{"model_name": "not-a-model", "enabled": True}]},
        headers=_auth(),
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_MODEL"


def test_create_pool_and_duplicate(eng):
    c = TestClient(app)
    r = c.post("/api/v1/admin/model-pools", json={"name": "finance"}, headers=_auth())
    assert r.status_code == 200 and r.json()["name"] == "finance"
    dup = c.post("/api/v1/admin/model-pools", json={"name": "finance"}, headers=_auth())
    assert dup.status_code == 409
    bad = c.post("/api/v1/admin/model-pools", json={"name": ""}, headers=_auth())
    assert bad.status_code == 400


def test_delete_pool_in_use_rejected(eng):
    c = TestClient(app)
    r = c.request(
        "DELETE", "/api/v1/admin/model-pools/1", headers=_auth()
    )  # chen 在 default 池
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "POOL_IN_USE"


def test_delete_pool_after_moving_users(eng):
    c = TestClient(app)
    c.patch(
        "/api/v1/admin/users/2/pool", json={"model_pool_id": 2}, headers=_auth()
    )
    r = c.request("DELETE", "/api/v1/admin/model-pools/1", headers=_auth())
    assert r.status_code == 200
    # 用户池已迁移
    assert c.get("/api/v1/admin/users", headers=_auth()).json()["users"][1]["model_pool_id"] == 2


def test_set_user_pool_validation(eng):
    c = TestClient(app)
    assert c.patch("/api/v1/admin/users/999/pool", json={"model_pool_id": 1}, headers=_auth()).status_code == 404
    assert c.patch("/api/v1/admin/users/2/pool", json={"model_pool_id": 42}, headers=_auth()).status_code == 404
    ok = c.patch("/api/v1/admin/users/2/pool", json={"model_pool_id": None}, headers=_auth())
    assert ok.status_code == 200 and ok.json()["model_pool_id"] is None


def test_pool_endpoints_require_admin(eng):
    c = TestClient(app)
    assert c.get("/api/v1/admin/model-pools", headers=_auth("EMP002")).status_code == 403
    assert c.post("/api/v1/admin/model-pools", json={"name": "x"}, headers=_auth("EMP002")).status_code == 403
    assert c.request("DELETE", "/api/v1/admin/model-pools/1", headers=_auth("EMP002")).status_code == 403


def test_admin_models_catalog_requires_admin(eng):
    c = TestClient(app)
    assert c.get("/api/v1/admin/models", headers=_auth("EMP002")).status_code == 403
    data = c.get("/api/v1/admin/models", headers=_auth()).json()
    ids = {m["id"] for m in data["models"]}
    assert "deepseek-chat" in ids and "bge-m3" in ids
