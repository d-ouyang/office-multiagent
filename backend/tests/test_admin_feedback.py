"""管理端「意见反馈」接口测试（v2.0.0-p2.3）——只读：统计 + 筛选 + 分页 + 越权。"""
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
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, trace TEXT, feedback TEXT, feedback_tags TEXT, feedback_comment TEXT, feedback_at TEXT)"))
        c.execute(text(
            "CREATE TABLE message_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id INTEGER NOT NULL, "
            "session_id TEXT NOT NULL, user_id INTEGER NOT NULL, rating TEXT NOT NULL, "
            "tags TEXT, comment TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        ))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (1, 'EMP001', 'dev', 'admin')"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (2, 'EMP002', 'chen', 'user')"))
        c.execute(text("INSERT INTO session (id, user_id) VALUES ('s1', 2)"))
        c.execute(text("INSERT INTO message (session_id, role, content) VALUES ('s1', 'assistant', '10月销售额为 6044 元')"))
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-admin-fb")
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)
    return engine


def _auth(emp: str = "EMP001") -> dict[str, str]:
    token = pyjwt.encode({"sub": emp, "tv": 0}, "test-secret-admin-fb", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed(engine, rating: str, tags: list[str], comment: str | None, mid: int = 1, uid: int = 2):
    import json

    with engine.begin() as c:
        c.execute(
            text("INSERT INTO message_feedback (message_id, session_id, user_id, rating, tags, comment) VALUES (:m, 's1', :u, :r, :t, :c)"),
            {"m": mid, "u": uid, "r": rating, "t": json.dumps(tags, ensure_ascii=False), "c": comment},
        )


def test_feedback_stats_and_list(eng):
    _seed(eng, "like", [], None)
    _seed(eng, "dislike", ["数据或数字有误"], "环比算错了")
    _seed(eng, "dislike", ["数据或数字有误", "回答不专业"], None)
    data = TestClient(app).get("/api/v1/admin/feedback", headers=_auth()).json()
    assert data["stats"]["total"] == 3
    assert data["stats"]["like"] == 1 and data["stats"]["dislike"] == 2
    assert data["stats"]["dislike_rate"] == round(2 / 3, 4)
    assert data["stats"]["top_tags"][0] == ["数据或数字有误", 2]
    assert data["total"] == 3
    top = data["items"][0]  # 时间倒序 = 最新一条
    assert top["rating"] == "dislike" and top["username"] == "chen"
    assert top["message_snippet"].startswith("10月销售额")
    assert "数据或数字有误" in top["tags"]


def test_feedback_filters_rating_tag_keyword(eng):
    _seed(eng, "like", [], None)
    _seed(eng, "dislike", ["工具调用有误"], "没查到")
    c = TestClient(app)
    only_like = c.get("/api/v1/admin/feedback", params={"rating": "like"}, headers=_auth()).json()
    assert only_like["total"] == 1 and only_like["items"][0]["rating"] == "like"
    # 统计口径不含 rating 筛选：总反馈仍是 2
    assert only_like["stats"]["total"] == 2
    by_tag = c.get("/api/v1/admin/feedback", params={"tag": "工具调用有误"}, headers=_auth()).json()
    assert by_tag["total"] == 1
    by_kw = c.get("/api/v1/admin/feedback", params={"q": "没查到"}, headers=_auth()).json()
    assert by_kw["total"] == 1


def test_feedback_requires_admin(eng):
    c = TestClient(app)
    r = c.get("/api/v1/admin/feedback", headers=_auth("EMP002"))
    assert r.status_code == 403
    anon = TestClient(app)
    assert anon.get("/api/v1/admin/feedback").status_code in (401, 403)
