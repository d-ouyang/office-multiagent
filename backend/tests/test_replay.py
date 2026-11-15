"""Phase D 回放端点测试（v2.2.0-p1.11）：四套日志按 run_id 合一 + 权限口径。"""
import json

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core import runtime_settings
from app.core.config import settings


@pytest.fixture()
def replay_env(monkeypatch):
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with eng.begin() as c:
        c.execute(text("CREATE TABLE user (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'done', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, trace TEXT, feedback TEXT, feedback_tags TEXT, feedback_comment TEXT, feedback_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE tool_invocation (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, tool_name TEXT, args_hash TEXT, args_preview TEXT, observation TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE tool_call_log (id VARCHAR(64) PRIMARY KEY, agent_run_id TEXT, tool TEXT, params TEXT, error TEXT, success INTEGER)"))
        c.execute(text("CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id INTEGER, actor_username TEXT, actor_role TEXT, action TEXT, target_type TEXT, target_id TEXT, target_label TEXT, detail TEXT, ip TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO user (id, employee_id, username, role) VALUES (1,'EMP001','dev','admin'), (2,'EMP002','wang','user')"))
        c.execute(text("INSERT INTO session (id, user_id) VALUES ('s-own', 1), ('s-other', 2)"))
        c.execute(text("INSERT INTO task (id, session_id, status, text, result, tokens_used, request_json) VALUES ('run-A', 's-own', 'done', '问', '答', 8312, '{\"model\":\"deepseek-chat\"}')"))
        c.execute(text("INSERT INTO message (session_id, role, content, trace) VALUES ('s-own','assistant','答', :t)"),
                  {"t": json.dumps([
                      {"type": "done", "run_id": "run-A", "seq": 1, "data": {}},
                      {"type": "done", "run_id": "run-B", "seq": 2, "data": {}},
                  ])})
        c.execute(text("INSERT INTO tool_invocation (run_id, tool_name, args_hash, args_preview, observation) VALUES ('run-A','query_orders','h1','{\"metric\":\"count\"}','{\"rows\":[]}')"))
        c.execute(text("INSERT INTO tool_call_log (id, agent_run_id, tool, params, success) VALUES ('tc1','run-A','query_orders','{}',1)"))
        c.execute(text("INSERT INTO token_ledger (user_id, task_id, model, reserve, settle) VALUES (1,'run-A','deepseek-chat',2000,8121)"))
        c.execute(text("INSERT INTO audit_log (actor_user_id, actor_username, actor_role, action, target_type, target_id, detail) VALUES (1,'dev','admin','run.dead_letter','task','run-A','{\"error\":\"boom\"}')"))
    monkeypatch.setattr("app.core.db.get_engine", lambda: eng)
    monkeypatch.setattr(runtime_settings, "_loaded", False)
    monkeypatch.setattr(runtime_settings, "_values", {})
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-p62c")

    from app.main import app

    client = TestClient(app)

    def token(uid: int) -> str:
        eid = "EMP001" if uid == 1 else "EMP002"
        return f"Bearer {__import__('jwt').encode({'sub': eid}, 'test-secret-p62c', algorithm='HS256')}"

    yield client, token, eng


def test_replay_aggregates_four_logs(replay_env):
    """判据：本人回放一次拿全四套日志，且 events 按 run_id 过滤（run-B 不混入）。"""
    client, token, _ = replay_env
    r = client.get("/api/v1/runs/run-A/replay", headers={"Authorization": token(1)})
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["run_id"] == "run-A" and body["run"]["tokens_used"] == 8312
    evs = [e["run_id"] for e in body["events"]]
    assert evs == ["run-A"], f"应只含本 run 事件，实际 {evs}"
    assert body["tools"]["invocations"][0]["tool_name"] == "query_orders"
    assert body["tools"]["call_log"][0]["tool"] == "query_orders"
    assert body["usage"][0]["settle"] == 8121
    assert body["dead_letter"][0]["action"] == "run.dead_letter"


def test_replay_other_user_404(replay_env):
    """非本人且非管理员 → 404（不暴露存在性，与会话权限同口径）。"""
    client, token, _ = replay_env
    r = client.get("/api/v1/runs/run-A/replay", headers={"Authorization": token(2)})
    assert r.status_code == 404


def test_replay_admin_can_view_any(replay_env):
    """admin 可回放任意 run。"""
    client, token, _ = replay_env
    r = client.get("/api/v1/runs/run-A/replay", headers={"Authorization": token(1)})
    assert r.status_code == 200  # dev 是 admin，看自己的
    # wang（普通用户）看自己的 run 才 200——补一个他人任务验证 admin 跨权
    eng = replay_env[2]
    with eng.begin() as c:
        c.execute(text("INSERT INTO task (id, session_id, status, text, result) VALUES ('run-C','s-other','done','x','y')"))
    r2 = client.get("/api/v1/runs/run-C/replay", headers={"Authorization": token(1)})
    assert r2.status_code == 200
    r3 = client.get("/api/v1/runs/run-C/replay", headers={"Authorization": token(2)})
    assert r3.status_code == 200  # 本人


def test_replay_missing_run_404(replay_env):
    client, token, _ = replay_env
    r = client.get("/api/v1/runs/run-NOPE/replay", headers={"Authorization": token(1)})
    assert r.status_code == 404
