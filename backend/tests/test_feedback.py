"""消息反馈闭环测试（v2.0.0-p2.1）——repo / API / 越权 / 覆盖保留流水。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.feedback_repo import FeedbackRepo, FeedbackValidationError
from app.main import app


@pytest.fixture
def eng(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, "
            "model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0, password_hash TEXT)"
        ))
        c.execute(text(
            "CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, model TEXT, "
            "title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        ))
        c.execute(text(
            "CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
            "role TEXT NOT NULL, content TEXT NOT NULL, trace TEXT, "
            "feedback TEXT, feedback_tags TEXT, feedback_comment TEXT, feedback_at TEXT, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        ))
        c.execute(text(
            "CREATE TABLE message_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id INTEGER NOT NULL, "
            "session_id TEXT NOT NULL, user_id INTEGER NOT NULL, rating TEXT NOT NULL, "
            "tags TEXT, comment TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        ))
        c.execute(text(
            "CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, "
            "model TEXT, settle INTEGER)"
        ))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (1, 'EMP001', 'dev', 'admin')"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (2, 'EMP002', 'chen', 'user')"))
        c.execute(text("INSERT INTO session (id, user_id, model) VALUES ('s1', 1, 'deepseek-chat')"))
        c.execute(text("INSERT INTO session (id, user_id, model) VALUES ('s2', 2, 'deepseek-chat')"))
        c.execute(text("INSERT INTO message (session_id, role, content) VALUES ('s1', 'assistant', '回答甲')"))
        c.execute(text("INSERT INTO message (session_id, role, content) VALUES ('s1', 'assistant', '回答乙')"))
        c.execute(text("INSERT INTO message (session_id, role, content) VALUES ('s1', 'user', '提问')"))
        c.execute(text("INSERT INTO message (session_id, role, content) VALUES ('s2', 'assistant', '别人的回答')"))
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-feedback")
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)
    return engine


def _auth(emp: str = "EMP001") -> dict[str, str]:
    import jwt as pyjwt

    token = pyjwt.encode({"sub": emp, "tv": 0}, "test-secret-feedback", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _fb(client, sid: str, mid: int, body: dict):
    return client.post(f"/api/v1/sessions/{sid}/messages/{mid}/feedback", json=body, headers=_auth())


# --------------------------------------------------------------------------- #
# 仓储层
# --------------------------------------------------------------------------- #

def test_submit_like_then_cancel(eng):
    repo = FeedbackRepo(eng)
    state = repo.submit("s1", 1, 1, "like")
    assert state["feedback"] == "like" and state["tags"] == []
    assert repo.cancel("s1", 1, 1) is True
    assert repo.current_state(1)["feedback"] is None
    # 取消后流水仍在（append-only，历史可查）
    with eng.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM message_feedback WHERE message_id = 1")).scalar()
    assert n == 1


def test_discover_requires_reason_dislike(eng):
    repo = FeedbackRepo(eng)
    with pytest.raises(FeedbackValidationError):
        repo.submit("s1", 1, 1, "dislike")  # 无 tag 无 comment
    with pytest.raises(FeedbackValidationError):
        repo.submit("s1", 1, 1, "dislike", tags=["不存在的标签"])
    state = repo.submit("s1", 1, 1, "dislike", tags=["数据或数字有误"], comment="环比算错了")
    assert state["feedback"] == "dislike" and state["tags"] == ["数据或数字有误"]
    assert state["comment"] == "环比算错了"


def test_second_dislike_overwrites_and_keeps_history(eng):
    """二次点踩：当前态覆盖；旧反馈保留在流水（PLAN §4.1 状态机）。"""
    repo = FeedbackRepo(eng)
    repo.submit("s1", 1, 1, "dislike", tags=["回答模糊、不具体"])
    repo.submit("s1", 1, 1, "dislike", tags=["数据或数字有误"], comment="数字对不上")
    state = repo.current_state(1)
    assert state["tags"] == ["数据或数字有误"] and state["comment"] == "数字对不上"
    with eng.connect() as c:
        rows = c.execute(
            text("SELECT rating, tags, comment FROM message_feedback WHERE message_id = 1 ORDER BY id")
        ).mappings().all()
    assert len(rows) == 2
    assert rows[0]["tags"] == '["回答模糊、不具体"]'
    assert rows[1]["tags"] == '["数据或数字有误"]'


def test_switch_like_dislike_overwrites(eng):
    repo = FeedbackRepo(eng)
    repo.submit("s1", 1, 1, "like")
    repo.submit("s1", 1, 1, "dislike", tags=["工具调用有误"])
    assert repo.current_state(1)["feedback"] == "dislike"


def test_get_message_for_ownership_and_role(eng):
    repo = FeedbackRepo(eng)
    assert repo.get_message_for("s1", 1, 1) is not None
    assert repo.get_message_for("s1", 1, 2) is None      # 别人的会话
    assert repo.get_message_for("s1", 3, 1) is None      # user 消息不可反馈
    assert repo.get_message_for("s2", 4, 1) is None      # 别人的消息


def test_comment_too_long(eng):
    repo = FeedbackRepo(eng)
    with pytest.raises(FeedbackValidationError):
        repo.submit("s1", 1, 1, "dislike", comment="x" * 201)


# --------------------------------------------------------------------------- #
# API 层
# --------------------------------------------------------------------------- #

def test_api_submit_and_cancel_roundtrip(eng):
    client = TestClient(app)
    r = _fb(client, "s1", 1, {"rating": "like"})
    assert r.status_code == 200
    assert r.json()["feedback"]["feedback"] == "like"
    # 历史消息带出反馈当前态
    msgs = client.get("/api/v1/sessions/s1/messages", headers=_auth()).json()["messages"]
    assistant = next(m for m in msgs if m["role"] == "assistant" and m["id"] == 1)
    assert assistant["feedback"]["rating"] == "like"
    # 取消
    d = client.delete("/api/v1/sessions/s1/messages/1/feedback", headers=_auth())
    assert d.status_code == 200 and d.json()["cancelled"] is True
    msgs = client.get("/api/v1/sessions/s1/messages", headers=_auth()).json()["messages"]
    assistant = next(m for m in msgs if m["id"] == 1)
    assert assistant["feedback"]["rating"] is None


def test_api_dislike_without_reason_400(eng):
    client = TestClient(app)
    r = _fb(client, "s1", 1, {"rating": "dislike"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_FEEDBACK"


def test_api_forbidden_returns_404_same_shape(eng):
    client = TestClient(app)
    # 别人的会话消息 → 404 同形（不区分不存在与无权）
    r = _fb(client, "s2", 4, {"rating": "like"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "MESSAGE_NOT_FOUND"
    # user 消息不可反馈
    r = _fb(client, "s1", 3, {"rating": "like"})
    assert r.status_code == 404
    # 未登录
    anon = TestClient(app)
    r = anon.post("/api/v1/sessions/s1/messages/1/feedback", json={"rating": "like"})
    assert r.status_code in (401, 403)


def test_api_second_dislike_overwrites_current_only(eng):
    client = TestClient(app)
    _fb(client, "s1", 2, {"rating": "dislike", "tags": ["回答不专业"]})
    _fb(client, "s1", 2, {"rating": "dislike", "tags": ["误解了我的问题"], "comment": "答非所问"})
    msgs = client.get("/api/v1/sessions/s1/messages", headers=_auth()).json()["messages"]
    m2 = next(m for m in msgs if m["id"] == 2)
    assert m2["feedback"]["tags"] == ["误解了我的问题"]
    assert m2["feedback"]["comment"] == "答非所问"
