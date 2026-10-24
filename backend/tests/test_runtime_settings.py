"""系统设置：全员一份，只有管理员能改，没改过时用环境变量默认值。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core import runtime_settings
from app.main import app


@pytest.fixture
def eng(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, "
            "role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0)"
        ))
        c.execute(text(
            "CREATE TABLE runtime_setting (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)"
        ))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (1, 'EMP001', 'dev', 'admin')"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (2, 'EMP002', 'chen', 'user')"))
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-settings")
    for mod in ("app.core.db", "app.core.identity"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)
    runtime_settings._loaded = False
    runtime_settings._values.clear()
    yield engine
    runtime_settings._loaded = False
    runtime_settings._values.clear()


def _auth(emp: str = "EMP001") -> dict[str, str]:
    import jwt as pyjwt

    token = pyjwt.encode({"sub": emp, "tv": 0}, "test-secret-settings", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_staff_can_read_admin_can_write(eng):
    client = TestClient(app)
    seen = client.get("/api/v1/settings", headers=_auth("EMP002"))
    assert seen.status_code == 200
    body = seen.json()
    assert body["editable"] is False
    assert any(item["key"] == "task_token_hard_limit" and item["scope"] == "system" for item in body["items"])

    denied = client.patch(
        "/api/v1/settings/task_token_hard_limit",
        json={"value": 80000},
        headers=_auth("EMP002"),
    )
    assert denied.status_code == 403

    saved = client.patch(
        "/api/v1/settings/task_token_hard_limit",
        json={"value": 80000},
        headers=_auth(),
    )
    assert saved.status_code == 200
    assert runtime_settings.task_token_limit() == 80000

    client.patch("/api/v1/settings/result_validation", json={"value": False}, headers=_auth())
    assert runtime_settings.result_validation_enabled() is False
