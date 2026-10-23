"""暂停与续跑（p7.1）——多原因暂停：quota / user / error；重跑式续跑 + 归属校验。"""
import json
import threading

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.events import EventType
from app.core.runs import RunCancelled, cancel, finish, is_running, register, should_cancel
from app.main import app
from app.orchestration.orchestrator import run_dag
from app.orchestration.react import StubBrain, run_react
from app.orchestration.tools import ToolRegistry
from app.core.decomposer import DAG, Subtask


def _dag(pairs):
    return DAG(subtasks=[Subtask(id=i, agent_type=f"{i}_agent", intent=i, depends_on=d) for i, d in pairs])


# --------------------------------------------------------------------------- #
# 运行登记表（暂停信号）
# --------------------------------------------------------------------------- #

def test_register_cancel_and_finish():
    ev = register("run-1", owner_id=7)
    assert is_running("run-1")
    assert cancel("run-1", 7) is True
    assert ev.is_set()
    finish("run-1")
    assert not is_running("run-1")


def test_cancel_rejects_other_owner():
    ev = register("run-2", owner_id=7)
    assert cancel("run-2", 8) is False  # 不是自己的任务：不发信号
    assert not ev.is_set()
    assert cancel("run-404", 7) is False  # 不在运行中
    finish("run-2")


def test_should_cancel_helper():
    assert should_cancel(None)() is False
    ev = threading.Event()
    assert should_cancel(ev)() is False
    ev.set()
    assert should_cancel(ev)() is True


# --------------------------------------------------------------------------- #
# 编排层协作式取消
# --------------------------------------------------------------------------- #

def test_run_react_raises_when_cancelled():
    with pytest.raises(RunCancelled):
        run_react("任务", StubBrain("答"), ToolRegistry(), should_cancel=lambda: True)


def test_run_dag_stops_before_next_subtask():
    dag = _dag([("a", []), ("b", ["a"])])
    calls: list[str] = []

    def runner(st, upstream=None):
        calls.append(st.id)
        return run_react(st.intent, StubBrain(f"{st.id}-done"), ToolRegistry())

    # 检查点：层开始 1 次 + 每个子任务前各 1 次 → 第 3 次（b 之前）命中，a 已执行
    flags = iter([False, False, True])
    with pytest.raises(RunCancelled):
        run_dag(
            dag, emitter=__import__("app.core.events", fromlist=["RunEventEmitter"]).RunEventEmitter("r", "t"),
            emit=lambda e: None, agent_runner=runner, should_cancel=lambda: next(flags, True),
        )
    assert calls == ["a"]


def test_run_task_paused_by_user(monkeypatch):
    from app.orchestration.graph import run_task

    ev = threading.Event()
    ev.set()  # 一开始就暂停
    result, events = run_task("查一下制度", cancel_event=ev, estimate=2000)
    assert result["status"] == "paused_user"
    assert result["result"] == "（已按用户要求暂停）"
    assert result["tokens_used"] == 2000  # 与保守结算一致（账实相符）
    assert events[-1].type == EventType.DONE
    assert events[-1].data["status"] == "paused_user"


def test_run_task_error_becomes_resumable_pause(monkeypatch):
    from app.orchestration import graph as g

    def boom(*a, **k):
        raise RuntimeError("LLM 网关炸了")

    monkeypatch.setattr(g, "run_react", boom)
    result, events = g.run_task("查一下制度")
    assert result["status"] == "paused_error"
    assert "LLM 网关炸了" in result["error"]
    assert any(e.type == EventType.ERROR for e in events)


def test_run_task_cancel_settles_conservatively(monkeypatch):
    # 取消按预扣额结算（不退），防"发起即暂停"套退款
    from app.core.token_pool import TokenPool
    from app.orchestration.graph import run_task

    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(
            text(
                "CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
                "task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', "
                "note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, 1000)"))
    pool = TokenPool(eng)
    ev = threading.Event()
    ev.set()
    result, _ = run_task("查一下制度", user_id=1, estimate=100, token_pool=pool, cancel_event=ev)
    assert result["status"] == "paused_user"
    assert pool.balance(1) == 900  # 预扣 100，settle actual=100（不退）


# --------------------------------------------------------------------------- #
# HTTP：暂停 / 任务详情 / 续跑
# --------------------------------------------------------------------------- #

@pytest.fixture
def eng(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as c:
        c.execute(text("CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, trace TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (1, 'EMP001', 'dev', 'admin')"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (2, 'EMP002', 'chen', 'user')"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, 100000)"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (2, 100000)"))
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-p71")
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)
    return engine


def _token(emp: str = "EMP001") -> str:
    return pyjwt.encode({"sub": emp, "tv": 0}, "test-secret-p71", algorithm="HS256")


def _auth(emp: str = "EMP001") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(emp)}"}


def _paused_task(eng, *, task_id="t-paused", session="s1", user_id=1, status="paused_insufficient_quota", text_="查一下年假制度"):
    with eng.begin() as c:
        c.execute(text("INSERT OR IGNORE INTO session (id, user_id) VALUES (:s, :u)"), {"s": session, "u": user_id})
        c.execute(
            text(
                "INSERT INTO task (id, session_id, status, text, result, tokens_used, pause_reason, pause_payload, request_json) "
                "VALUES (:i, :s, :st, :t, '', 0, 'quota', :pp, :rq)"
            ),
            {
                "i": task_id,
                "s": session,
                "st": status,
                "t": text_,
                "pp": json.dumps({"balance": 0, "needed": 2000}),
                "rq": json.dumps({"text": text_, "attachments": [], "model": None, "effort": None}),
            },
        )


def test_get_task_and_list_paused(eng):
    _paused_task(eng)
    c = TestClient(app)
    r = c.get("/api/v1/tasks/t-paused", headers=_auth())
    assert r.status_code == 200
    task = r.json()["task"]
    assert task["status"] == "paused_insufficient_quota"
    assert task["pause_payload"]["needed"] == 2000  # JSON 已解析
    listed = c.get("/api/v1/tasks", params={"status": "paused_insufficient_quota"}, headers=_auth())
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()["tasks"]] == ["t-paused"]


def test_task_detail_rejects_other_user(eng):
    _paused_task(eng)
    c = TestClient(app)
    r = c.get("/api/v1/tasks/t-paused", headers=_auth("EMP002"))
    assert r.status_code == 404  # 不泄露他人任务存在性


def test_pause_returns_409_when_not_running(eng):
    c = TestClient(app)
    r = c.post("/api/v1/tasks/whatever/pause", headers=_auth())
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NOT_RUNNING"


def test_pause_forbidden_for_other_owner(eng):
    from app.core import runs

    ev = runs.register("run-x", owner_id=1)
    try:
        c = TestClient(app)
        r = c.post("/api/v1/tasks/run-x/pause", headers=_auth("EMP002"))
        assert r.status_code == 403
        assert not ev.is_set()
        ok = c.post("/api/v1/tasks/run-x/pause", headers=_auth("EMP001"))
        assert ok.status_code == 200 and ev.is_set()
    finally:
        runs.finish("run-x")


def test_resume_reruns_paused_task(eng):
    _paused_task(eng)
    c = TestClient(app)
    r = c.post("/api/v1/tasks/t-paused/resume", headers=_auth())
    assert r.status_code == 200
    assert "ndjson" in r.headers["content-type"]
    lines = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    assert lines and lines[-1]["type"] == "done"
    # 新任务行：retry_of 指回原任务，原任务保持不变
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT id, retry_of, status FROM task ORDER BY created_at")).mappings().all()
    assert len(rows) == 2
    retried = [r for r in rows if r["retry_of"] == "t-paused"]
    assert len(retried) == 1 and retried[0]["id"] != "t-paused"


def test_resume_rejects_done_task(eng):
    _paused_task(eng, status="done")
    c = TestClient(app)
    r = c.post("/api/v1/tasks/t-paused/resume", headers=_auth())
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NOT_RESUMABLE"


def test_resume_rejects_other_user(eng):
    _paused_task(eng)
    c = TestClient(app)
    r = c.post("/api/v1/tasks/t-paused/resume", headers=_auth("EMP002"))
    assert r.status_code == 404


def test_resume_requires_login(eng):
    _paused_task(eng)
    c = TestClient(app)
    assert c.post("/api/v1/tasks/t-paused/resume").status_code == 401
