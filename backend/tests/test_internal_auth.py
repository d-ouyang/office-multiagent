"""内部鉴权测试（§13.3，参考 RAG internal-auth.client.ts；用户点5）。

验证：X-Internal-Token 正确放行、错误/缺失拒绝（fail-closed），
且后端 PyJWT 侧与 NestJS passport-jwt 是【不同层】，互不冲突。
需安装 app 依赖（pytest + fastapi）。
"""
import pytest
from fastapi.testclient import TestClient

from app.core import internal_auth
from app.main import app


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(internal_auth.settings, "internal_shared_secret", "topsecret")
    yield "topsecret"


def test_verify_missing_secret_is_fail_closed(monkeypatch):
    monkeypatch.setattr(internal_auth.settings, "internal_shared_secret", "")
    assert internal_auth.verify_internal_token("anything") is False


def test_ping_ok_with_token(secret):
    c = TestClient(app)
    r = c.get("/api/v1/internal/auth/ping", headers={"X-Internal-Token": secret})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_ping_401_without_token(secret):
    c = TestClient(app)
    r = c.get("/api/v1/internal/auth/ping")
    assert r.status_code == 401


def test_ping_401_wrong_token(secret):
    c = TestClient(app)
    r = c.get("/api/v1/internal/auth/ping", headers={"X-Internal-Token": "wrong"})
    assert r.status_code == 401
