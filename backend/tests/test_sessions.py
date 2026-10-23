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
        c.execute(text("CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT UNIQUE, username TEXT, password_hash TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0, created_at TEXT)"))
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, trace TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
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


# ---------- p6.5 模型选择 ----------
def test_update_session_model_flow(client):
    sid = client.post("/api/v1/sessions", json={}, headers=_auth(_token())).json()["session_id"]
    # 未知模型 → 400（fail-closed）
    r = client.patch(f"/api/v1/sessions/{sid}", json={"model": "no-such"}, headers=_auth(_token()))
    assert r.status_code == 400 and r.json()["detail"]["code"] == "BAD_MODEL"
    # 合法模型 → ok（p6.8 模型列表重构后用现存 id）
    r = client.patch(f"/api/v1/sessions/{sid}", json={"model": "deepseek-chat"}, headers=_auth(_token()))
    assert r.status_code == 200
    from app.core.db import get_engine
    from app.core.session_repo import SessionRepo

    assert SessionRepo(get_engine()).get_session_model(sid) == "deepseek-chat"


def test_tasks_rejects_unknown_model(client):
    r = client.post(
        "/api/v1/tasks",
        json={"text": "hi", "model": "no-such"},
        headers=_auth(_token()),
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "BAD_MODEL"


def test_run_task_passes_model_to_brain(monkeypatch):
    # p6.5：run_task(model=...) 必须透传到 single_node 的 make_brain
    import app.orchestration.graph as graph_mod
    from app.orchestration.react import AgentResult

    captured: dict = {}
    real_make_brain = graph_mod.make_brain

    def spy_make_brain(tools, **kwargs):
        captured.update(kwargs)
        return real_make_brain(tools, **kwargs)

    monkeypatch.setattr(graph_mod, "make_brain", spy_make_brain)
    monkeypatch.setattr(graph_mod, "build_default_registry", lambda engine, **_kwargs: __import__("app.orchestration.tools", fromlist=["ToolRegistry"]).ToolRegistry())
    result, events = graph_mod.run_task("查年假", model="qwen-plus")
    assert captured.get("model_id") == "qwen-plus"
    assert result["status"] == "done"


def test_run_task_effort_only_for_reasoning_models(monkeypatch):
    import app.orchestration.graph as graph_mod
    from app.orchestration.react import StubBrain

    captured: dict = {}

    def spy(tools, **kwargs):
        captured.update(kwargs)
        return StubBrain("ok")

    monkeypatch.setattr(graph_mod, "make_brain", spy)
    monkeypatch.setattr(
        graph_mod, "build_default_registry",
        lambda engine, **_kwargs: __import__("app.orchestration.tools", fromlist=["ToolRegistry"]).ToolRegistry(),
    )
    graph_mod.run_task("hi", model="deepseek-v4-flash-sf", effort="low")
    assert captured.get("reasoning_effort") == "high"
    captured.clear()
    graph_mod.run_task("hi", model="deepseek-v4-flash-sf", effort="high")
    assert captured.get("reasoning_effort") == "high"
    captured.clear()
    graph_mod.run_task("hi", model="deepseek-v4-flash-sf", effort="max")
    assert captured.get("reasoning_effort") == "max"
    captured.clear()
    graph_mod.run_task("hi", model="deepseek-v4.1-flash-sf", effort="low")
    assert captured.get("reasoning_effort") == "low"
    captured.clear()
    graph_mod.run_task("hi", model="deepseek-chat", effort="max")
    assert captured.get("reasoning_effort") is None
    captured.clear()
    graph_mod.run_task("hi", model="deepseek-reasoner", effort="max")
    assert captured.get("reasoning_effort") is None


# ---------- p6.7 trace 过程落库 ----------
def test_trace_persisted_and_readable(client):
    # assistant 消息带 trace：落库后历史回读能重建过程事件
    from app.core.db import get_engine
    from app.core.session_repo import SessionRepo
    import json as _json

    sid = client.post("/api/v1/sessions", json={}, headers=_auth(_token())).json()["session_id"]
    trace = _json.dumps(
        [
            {"type": "thinking_delta", "data": {"delta": "想"}},
            {"type": "content_delta", "data": {"delta": "答"}},
        ],
        ensure_ascii=False,
    )
    SessionRepo(get_engine()).append_message(sid, "assistant", "答", trace=trace)
    msgs = client.get(f"/api/v1/sessions/{sid}/messages", headers=_auth(_token())).json()["messages"]
    assert msgs[-1]["trace"] is not None
    assert _json.loads(msgs[-1]["trace"])[0]["type"] == "thinking_delta"


# ---------- p6.7 trace 过程落库 ----------
def test_trace_persisted_and_readable(client):
    # assistant 消息带 trace：落库后历史回读能重建过程事件
    from app.core.db import get_engine
    from app.core.session_repo import SessionRepo
    import json as _json

    sid = client.post("/api/v1/sessions", json={}, headers=_auth(_token())).json()["session_id"]
    trace = _json.dumps(
        [
            {"type": "thinking_delta", "data": {"delta": "想"}},
            {"type": "content_delta", "data": {"delta": "答"}},
        ],
        ensure_ascii=False,
    )
    SessionRepo(get_engine()).append_message(sid, "assistant", "答", trace=trace)
    msgs = client.get(f"/api/v1/sessions/{sid}/messages", headers=_auth(_token())).json()["messages"]
    assert msgs[-1]["trace"] is not None
    assert _json.loads(msgs[-1]["trace"])[0]["type"] == "thinking_delta"


def test_rewind_keeps_prefix_and_drops_the_rest(client):
    from app.core.db import get_engine
    from app.core.session_repo import SessionRepo

    sid = client.post("/api/v1/sessions", json={}, headers=_auth(_token())).json()["session_id"]
    repo = SessionRepo(get_engine())
    for role, content in (("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2")):
        repo.append_message(sid, role, content)
    r = client.post(f"/api/v1/sessions/{sid}/rewind", json={"keep": 2}, headers=_auth(_token()))
    assert r.status_code == 200 and r.json()["deleted"] == 2
    msgs = client.get(f"/api/v1/sessions/{sid}/messages", headers=_auth(_token())).json()["messages"]
    assert [m["content"] for m in msgs] == ["q1", "a1"]


def test_rewind_rejects_negative_and_foreign_session(client):
    from app.core.db import get_engine
    from app.core.session_repo import SessionRepo

    sid = client.post("/api/v1/sessions", json={}, headers=_auth(_token())).json()["session_id"]
    bad = client.post(f"/api/v1/sessions/{sid}/rewind", json={"keep": -1}, headers=_auth(_token()))
    assert bad.status_code == 400
    other = SessionRepo(get_engine()).create_session(2)
    foreign = client.post(f"/api/v1/sessions/{other}/rewind", json={"keep": 0}, headers=_auth(_token()))
    assert foreign.status_code == 404


def test_messages_pick_up_model_from_ledger(client):
    from app.core.db import get_engine
    from app.core.session_repo import SessionRepo

    sid = client.post("/api/v1/sessions", json={}, headers=_auth(_token())).json()["session_id"]
    repo = SessionRepo(get_engine())
    repo.append_message(sid, "user", "问")
    repo.append_message(sid, "assistant", "答")
    with get_engine().begin() as conn:
        conn.execute(
            text("INSERT INTO token_ledger (user_id, task_id, model, settle) VALUES (1, 't1', 'deepseek-chat', 1200)")
        )
    msgs = client.get(f"/api/v1/sessions/{sid}/messages", headers=_auth(_token())).json()["messages"]
    assistant = msgs[-1]
    assert assistant["model"] == "deepseek-chat"
    assert assistant["tokens"] == 1200


def test_quota_usage_summary_counts_settles(client):
    from app.core.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text("INSERT INTO token_ledger (user_id, task_id, model, settle) VALUES (1, 't1', 'deepseek-chat', 50)")
        )
    body = client.get("/api/v1/quota", headers=_auth(_token())).json()
    assert body["usage"]["total_tokens"] == 50
    assert body["usage"]["total_count"] == 1
    assert body["ledger"][0]["created_at"].endswith("Z")
    assert "T" in body["ledger"][0]["created_at"]


def test_tasks_rejects_unknown_effort(client):
    r = client.post(
        "/api/v1/tasks",
        json={"text": "hi", "effort": "ultra"},
        headers=_auth(_token()),
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "BAD_EFFORT"
