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


def test_health_exposes_open_fds():
    """v2.0.0-p2.4：health 带出进程句柄数（句柄耗尽曾致全接口 500，用于提前观测泄漏）。"""
    c = TestClient(app)
    body = c.get("/api/v1/health").json()
    # Linux 下 /proc/self/fd 可读 → 具体数字；其它平台为 None（不报错即可）
    assert body.get("open_fds") is None or isinstance(body["open_fds"], int)


def test_health_exposes_rss_mb():
    """v2.0.0-p2.6：health 带出 RSS 内存（OOM 复盘：1.8GB 涨爆被杀且无人重启）。"""
    c = TestClient(app)
    body = c.get("/api/v1/health").json()
    assert body.get("rss_mb") is None or (isinstance(body["rss_mb"], (int, float)) and body["rss_mb"] > 0)
