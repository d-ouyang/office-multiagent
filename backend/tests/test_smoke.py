"""冒烟测试：不依赖外部服务，验证 app 可导入、路由结构正确。

可在沙箱直接跑（无需 docker / 无需 MySQL/Redis/Chroma）：
    pip install fastapi pydantic-settings sqlalchemy redis httpx pytest
    pytest backend/tests/test_smoke.py
"""
from fastapi.testclient import TestClient

from app.main import app


def test_root():
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "office-multiagent"


def test_health_structure():
    c = TestClient(app)
    r = c.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    for svc in ("mysql", "redis", "chroma"):
        assert svc in body["services"]
        assert "ok" in body["services"][svc]
