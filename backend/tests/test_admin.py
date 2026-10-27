"""管理端最小版（p7.1）：用户列表 + 充值 + 账本；role 校验 fail-closed。"""
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
        # p6.26：概览/任务监控要查 task 与 session
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (1, 'EMP001', 'dev', 'admin')"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (2, 'EMP002', 'chen', 'user')"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, 100000)"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (2, 500)"))
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-admin")
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)
    return engine


def _auth(emp: str = "EMP001") -> dict[str, str]:
    token = pyjwt.encode({"sub": emp, "tv": 0}, "test-secret-admin", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_users_list_requires_admin(eng):
    c = TestClient(app)
    r = c.get("/api/v1/admin/users", headers=_auth("EMP002"))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "FORBIDDEN"


def test_users_list_includes_balance_and_search(eng):
    c = TestClient(app)
    r = c.get("/api/v1/admin/users", headers=_auth())
    assert r.status_code == 200
    users = {u["username"]: u for u in r.json()["users"]}
    assert users["dev"]["balance"] == 100000
    assert users["chen"]["balance"] == 500
    found = c.get("/api/v1/admin/users", params={"q": "chen"}, headers=_auth()).json()["users"]
    assert [u["username"] for u in found] == ["chen"]


def test_recharge_updates_balance_and_ledger(eng):
    c = TestClient(app)
    r = c.post(
        "/api/v1/admin/users/2/recharge",
        json={"amount": 5000, "note": "月度补充"},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["balance"] == 5500
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT kind, note, reserve, settle FROM token_ledger WHERE user_id=2 ORDER BY id DESC LIMIT 1")
        ).mappings().first()
    assert row["kind"] == "recharge"
    assert row["reserve"] is None and row["settle"] is None
    assert "月度补充" in row["note"] and "操作人 1" in row["note"]
    # 用户自己 /quota 能看到充值流水（kind 字段）
    quota = c.get("/api/v1/quota", headers=_auth("EMP002")).json()
    assert any(item["kind"] == "recharge" for item in quota["ledger"])


def test_recharge_creates_wallet_when_missing(eng):
    with eng.begin() as c:
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (3, 'EMP003', 'zhao', 'user')"))
    resp = TestClient(app).post(
        "/api/v1/admin/users/3/recharge", json={"amount": 800}, headers=_auth()
    )
    assert resp.status_code == 200 and resp.json()["balance"] == 800


@pytest.mark.parametrize("amount", [0, -5, 10_000_001])
def test_recharge_rejects_bad_amount(eng, amount):
    r = TestClient(app).post(
        "/api/v1/admin/users/2/recharge", json={"amount": amount}, headers=_auth()
    )
    assert r.status_code == 400


def test_recharge_unknown_user_404(eng):
    r = TestClient(app).post(
        "/api/v1/admin/users/999/recharge", json={"amount": 100}, headers=_auth()
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "USER_NOT_FOUND"


def test_ledger_requires_admin_and_returns_rows(eng):
    c = TestClient(app)
    assert c.get("/api/v1/admin/users/2/ledger", headers=_auth("EMP002")).status_code == 403
    c.post("/api/v1/admin/users/2/recharge", json={"amount": 300}, headers=_auth())
    r = c.get("/api/v1/admin/users/2/ledger", headers=_auth())
    assert r.status_code == 200
    assert r.json()["ledger"][0]["kind"] == "recharge"


def test_admin_endpoints_require_login(eng):
    c = TestClient(app)
    assert c.get("/api/v1/admin/users").status_code == 401
    assert c.post("/api/v1/admin/users/2/recharge", json={"amount": 1}).status_code == 401


# --------------------------------------------------------------------------- #
# p6.26：概览 / 用量 / 任务监控
# --------------------------------------------------------------------------- #

def test_run_trace_summary_and_overview_fields(eng):
    import json
    from app.core.run_trace import summarize

    events = [
        {"type": "tool_call_start", "run_id": "run-1", "data": {"name": "query_orders"}},
        {"type": "tool_call_start", "data": {"name": "rag_retrieve"}},
        {"type": "observation", "data": {"text": "office_username=dev；rag_username=office-service；identity_mismatch=true"}},
        {"type": "observation", "data": {"text": "结果校验：终答中的数字 9999 未在工具观察或任务原文中出现"}},
    ]
    summary = summarize(events, request={"model": "deepseek-chat"})
    assert summary["tools"] == ["query_orders", "rag_retrieve"]
    assert summary["rag_called"] and summary["identity_mismatch"]
    assert summary["validation_mismatch"]

    with eng.begin() as conn:
        conn.execute(text("INSERT INTO session (id, user_id) VALUES ('s1', 2)"))
        conn.execute(text(
            "INSERT INTO task (id, session_id, status, text, pause_reason, request_json) "
            "VALUES ('run-1', 's1', 'done', '看看上海', NULL, :r)"
        ), {"r": json.dumps({"model": "deepseek-chat"})})
        conn.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, trace TEXT, feedback TEXT, feedback_tags TEXT, feedback_comment TEXT, feedback_at TEXT)"))
        conn.execute(text("INSERT INTO message (session_id, role, content, trace) VALUES ('s1', 'assistant', 'ok', :t)"), {"t": json.dumps(events)})
    client = TestClient(app)
    listed = client.get("/api/v1/admin/runs", params={"flag": "rag"}, headers=_auth())
    assert listed.status_code == 200
    assert any(row["id"] == "run-1" for row in listed.json()["tasks"])
    detail = client.get("/api/v1/admin/runs/run-1", headers=_auth()).json()
    assert detail["tool_summary"] == "query_orders → rag_retrieve"
    overview = client.get("/api/v1/admin/overview", headers=_auth()).json()
    assert "tasks_failed_7d" in overview and "paused_by_reason" in overview
    assert overview["validation_mismatches"] == 1


def test_overview_counts_and_zero_safe(eng):
    c = TestClient(app)
    data = c.get("/api/v1/admin/overview", headers=_auth()).json()
    assert data["users_total"] == 2
    assert data["balance_total"] == 100500  # 100000 + 500
    assert data["tasks_total"] == 0 and data["month_tokens"] == 0

    c.post("/api/v1/admin/users/2/recharge", json={"amount": 3000}, headers=_auth())
    data2 = c.get("/api/v1/admin/overview", headers=_auth()).json()
    assert data2["recharge_total"] == 3000  # 只统计有金额的充值
    assert data2["recharge_count"] == 1
    assert data2["balance_total"] == 103500


def test_overview_month_tokens_only_task_settles(eng):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, kind, reserve, settle) VALUES (1, 't1', 'task', 2000, 1500)"))
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, kind, reserve, settle) VALUES (1, 't2', 'task', 2000, NULL)"))
        conn.execute(text("INSERT INTO token_ledger (user_id, kind, amount) VALUES (1, 'recharge', 9999)"))
    data = TestClient(app).get("/api/v1/admin/overview", headers=_auth()).json()
    assert data["month_tokens"] == 1500  # 只计 settle 行；预扣行/充值行不算
    assert data["month_calls"] == 1


def test_usage_series_by_day(eng):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, model, kind, reserve, settle, created_at) VALUES (1, 'a', 'deepseek-chat', 'task', 2000, 100, '2026-10-21 10:00:00')"))
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, model, kind, reserve, settle, created_at) VALUES (1, 'b', 'deepseek-chat', 'task', 2000, 200, '2026-10-21 11:00:00')"))
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, model, kind, reserve, settle, created_at) VALUES (2, 'c', 'qwen3.5-9b-sf', 'task', 2000, 300, '2026-10-22 12:00:00')"))
    data = TestClient(app).get("/api/v1/admin/usage?days=30", headers=_auth()).json()
    series = {row["date"]: row for row in data["series"]}
    assert len(data["series"]) == 30
    assert series["2026-10-21"]["tokens"] == 300 and series["2026-10-21"]["calls"] == 2
    assert series["2026-10-21"]["by_model"]["deepseek-chat"] == 300
    assert series["2026-10-22"]["tokens"] == 300
    assert series["2026-10-22"]["by_model"]["qwen3.5-9b-sf"] == 300
    assert data["models"][0] == "deepseek-chat"


def test_admin_tasks_global_with_username_and_filter(eng):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO session (id, user_id) VALUES ('s1', 1)"))
        conn.execute(text("INSERT INTO session (id, user_id) VALUES ('s2', 2)"))
        conn.execute(
            text("INSERT INTO task (id, session_id, status, text, tokens_used, pause_reason) VALUES ('t-a', 's1', 'done', '查年假', 120, NULL)")
        )
        conn.execute(
            text("INSERT INTO task (id, session_id, status, text, tokens_used, pause_reason) VALUES ('t-b', 's2', 'paused_user', '清洗表格', 0, 'user')")
        )
    c = TestClient(app)
    rows = c.get("/api/v1/admin/tasks", headers=_auth()).json()["tasks"]
    assert {r["id"] for r in rows} == {"t-a", "t-b"}
    by_id = {r["id"]: r for r in rows}
    assert by_id["t-a"]["username"] == "dev" and by_id["t-a"]["employee_id"] == "EMP001"
    assert by_id["t-b"]["username"] == "chen" and by_id["t-b"]["pause_reason"] == "user"
    assert by_id["t-b"]["employee_id"] == "EMP002"
    paused = c.get("/api/v1/admin/tasks?status=paused_user", headers=_auth()).json()["tasks"]
    assert [r["id"] for r in paused] == ["t-b"]


def test_admin_tasks_requires_admin(eng):
    assert TestClient(app).get("/api/v1/admin/tasks", headers=_auth("EMP002")).status_code == 403


def test_admin_tasks_q_date_and_employee_id(eng):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO session (id, user_id) VALUES ('s1', 1)"))
        conn.execute(text("INSERT INTO session (id, user_id) VALUES ('s2', 2)"))
        conn.execute(text(
            "INSERT INTO task (id, session_id, status, text, tokens_used, created_at) "
            "VALUES ('t-a', 's1', 'done', '查年假', 120, '2026-03-15 10:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO task (id, session_id, status, text, tokens_used, created_at) "
            "VALUES ('t-b', 's2', 'paused_user', '清洗表格', 0, '2026-03-16 10:00:00')"
        ))
    c = TestClient(app)
    by_emp = c.get("/api/v1/admin/tasks", params={"q": "EMP002"}, headers=_auth()).json()["tasks"]
    assert [r["id"] for r in by_emp] == ["t-b"]
    assert by_emp[0]["employee_id"] == "EMP002"
    by_name = c.get("/api/v1/admin/tasks", params={"q": "dev"}, headers=_auth()).json()["tasks"]
    assert [r["id"] for r in by_name] == ["t-a"]
    day = c.get("/api/v1/admin/tasks", params={"date": "2026_03_15"}, headers=_auth()).json()["tasks"]
    assert [r["id"] for r in day] == ["t-a"]
    day2 = c.get("/api/v1/admin/tasks", params={"date": "2026-03-16"}, headers=_auth()).json()["tasks"]
    assert [r["id"] for r in day2] == ["t-b"]


def test_users_role_filter(eng):
    c = TestClient(app)
    admins = c.get("/api/v1/admin/users", params={"role": "admin"}, headers=_auth()).json()["users"]
    assert {u["username"] for u in admins} == {"dev"}
    members = c.get("/api/v1/admin/users", params={"role": "user"}, headers=_auth()).json()["users"]
    assert {u["username"] for u in members} == {"chen"}


def test_users_exact_search_and_balance_filter(eng):
    c = TestClient(app)
    fuzzy = c.get("/api/v1/admin/users", params={"q": "ch"}, headers=_auth()).json()["users"]
    assert fuzzy == []
    exact = c.get("/api/v1/admin/users", params={"q": "chen"}, headers=_auth()).json()["users"]
    assert [u["username"] for u in exact] == ["chen"]
    low = c.get("/api/v1/admin/users", params={"balance_max": 500}, headers=_auth()).json()["users"]
    assert {u["username"] for u in low} == {"chen"}
    high = c.get("/api/v1/admin/users", params={"balance_min": 1000}, headers=_auth()).json()["users"]
    assert {u["username"] for u in high} == {"dev"}
    gt = c.get("/api/v1/admin/users", params={"balance": 500, "balance_op": "gt"}, headers=_auth()).json()["users"]
    assert {u["username"] for u in gt} == {"dev"}
    lt = c.get("/api/v1/admin/users", params={"balance": 1000, "balance_op": "lt"}, headers=_auth()).json()["users"]
    assert {u["username"] for u in lt} == {"chen"}


def test_users_total_used_and_ledger_page(eng):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, kind, reserve, settle) VALUES (2, 't1', 'task', 2000, 800)"))
        conn.execute(text("INSERT INTO token_ledger (user_id, task_id, kind, reserve, settle) VALUES (2, 't2', 'task', 2000, 200)"))
    c = TestClient(app)
    users = {u["username"]: u for u in c.get("/api/v1/admin/users", headers=_auth()).json()["users"]}
    assert users["chen"]["total_used"] == 1000
    page = c.get("/api/v1/admin/users/2/ledger", params={"page": 1, "page_size": 1}, headers=_auth()).json()
    assert page["total"] == 2 and len(page["ledger"]) == 1


def test_admin_tasks_task_id_and_session(eng):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO session (id, user_id) VALUES ('s1', 1)"))
        conn.execute(text("INSERT INTO task (id, session_id, status, text, tokens_used) VALUES ('task-1', 's1', 'done', '很长的摘要用来悬停', 30)"))
    row = TestClient(app).get("/api/v1/admin/tasks", params={"task_id": "task-1"}, headers=_auth()).json()["tasks"][0]
    assert row["session_id"] == "s1"
    assert row["text"] == "很长的摘要用来悬停"
    assert "duration_ms" in row


def test_run_detail_includes_flow(eng):
    import json
    events = [
        {"type": "thinking_delta", "run_id": "run-flow", "ts": 1000, "data": {"delta": "识别意图：查数"}},
        {"type": "tool_call_start", "run_id": "run-flow", "ts": 1500, "data": {"name": "query_orders"}},
        {"type": "done", "run_id": "run-flow", "ts": 3000, "data": {"status": "done"}},
    ]
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO session (id, user_id) VALUES ('s1', 2)"))
        conn.execute(text("INSERT INTO task (id, session_id, status, text) VALUES ('run-flow', 's1', 'done', '查订单')"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS message (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, trace TEXT, feedback TEXT, feedback_tags TEXT, feedback_comment TEXT, feedback_at TEXT)"))
        conn.execute(text("INSERT INTO message (session_id, role, content, trace) VALUES ('s1', 'assistant', 'ok', :t)"), {"t": json.dumps(events)})
    detail = TestClient(app).get("/api/v1/admin/runs/run-flow", headers=_auth()).json()
    assert detail["duration_ms"] == 2000
    assert detail["flow"]["path"][0] == "received"
    assert detail["flow"]["flow_path"][0] == "received"
    assert "tools" in detail["flow"]["flow_path"]
    assert "done" in detail["flow"]["flow_path"]
    assert any(n["key"] == "tools" for n in detail["flow"]["nodes"])
    assert any(e["from"] == "route" and e["to"] == "tools" for e in detail["flow"]["edges"])
