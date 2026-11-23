"""v2.4.5：HITL 待确认的收敛——superseded 状态 / 跳过落库 / 徽章只认最新一条 / 流式心跳。

真跑背景（线上 office.nianan.site）：
- task 行是"跑完才 INSERT"，用户等不及重发不会回收旧的 paused_input；
- 侧栏徽章是 EXISTS(会话内存在 paused_input)、刷新横幅是"最近 10 条里 find 任意 paused"，
  于是答完旧暂停、又跑了几轮 done 之后，刷新照样弹同一张问题卡（实测一个会话 3 条僵尸）；
- 前端"跳过"只改本地 state，不落库，刷新即复现。

本文件盯四件事：
1. 新任务一发出 → 该会话旧的 paused_input 全部 superseded；
2. 徽章只看最新一条任务（老 paused + 新 done → 不挂徽章）；
3. /answer 的 action=skip 落库，重复 skip 返回 409；
4. 心跳线程按间隔产出 heartbeat 事件，停表后不再产出。
"""
import queue
import threading

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.events import EventType
from app.core.session_repo import SessionRepo
from app.main import app

SECRET = "test-jwt-secret-v245"


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with eng.begin() as c:
        c.execute(text("CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT UNIQUE, username TEXT, password_hash TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0, created_at TEXT)"))
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, trace TEXT, feedback TEXT, feedback_tags TEXT, feedback_comment TEXT, feedback_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role, model_pool_id) VALUES (1,'EMP001','dev','admin',3)"))
        c.execute(text("INSERT INTO session (id, user_id, title) VALUES ('s-1', 1, '测试会话')"))
    return eng


@pytest.fixture
def repo(engine, monkeypatch):
    monkeypatch.setattr("app.core.session_repo.get_engine", lambda: engine)
    return SessionRepo(engine)


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr("app.core.db.get_engine", lambda: engine)
    monkeypatch.setattr("app.core.identity.get_engine", lambda: engine)
    monkeypatch.setattr("app.core.session_repo.get_engine", lambda: engine)
    return TestClient(app)


def _token() -> str:
    return pyjwt.encode(
        {"sub": "EMP001", "username": "dev", "role": "admin"}, SECRET, algorithm="HS256"
    )


def _add_task(repo: SessionRepo, tid: str, status: str, created_at: str, session: str = "s-1") -> None:
    repo.record_task(tid, session, "导出一份订单明细表", "", 100, status, pause_reason="need_input" if status == "paused_input" else None)
    # created_at 由 record_task 写 DEFAULT，这里改成显式值以构造"新旧"关系
    with repo.engine.begin() as conn:
        conn.execute(text("UPDATE task SET created_at = :c WHERE id = :i"), {"c": created_at, "i": tid})


# --------------------------------------------------------------------------- #
# 1. 新任务作废旧暂停
# --------------------------------------------------------------------------- #

def test_supersede_session_paused_only_touches_paused_input(repo):
    _add_task(repo, "t-old-1", "paused_input", "2026-11-23 08:00:00")
    _add_task(repo, "t-old-2", "paused_input", "2026-11-23 08:01:00")
    _add_task(repo, "t-done", "done", "2026-11-23 08:02:00")

    n = repo.supersede_session_paused("s-1")

    assert n == 2
    assert repo.get_task("t-old-1")["status"] == "superseded"
    assert repo.get_task("t-old-2")["status"] == "superseded"
    assert repo.get_task("t-done")["status"] == "done"  # 终态不许被改写
    # 作废后不再带 pause_reason：管理端"待补充"口径也不会把它算进去
    assert repo.get_task("t-old-1")["pause_reason"] is None


def test_supersede_task_rejects_non_paused(repo):
    _add_task(repo, "t-done-2", "done", "2026-11-23 08:03:00")
    assert repo.supersede_task("t-done-2") is False
    assert repo.get_task("t-done-2")["status"] == "done"


# --------------------------------------------------------------------------- #
# 2. 侧栏徽章只认最新一条任务
# --------------------------------------------------------------------------- #

def test_pending_badge_ignores_stale_paused_when_latest_is_done(repo):
    _add_task(repo, "t-paused", "paused_input", "2026-11-23 08:00:00")
    _add_task(repo, "t-latest", "done", "2026-11-23 08:05:00")

    sessions = {s["session_id"]: s for s in repo.list_sessions(1)}

    assert sessions["s-1"]["has_pending_input"] is False


def test_pending_badge_true_when_latest_is_paused(repo):
    _add_task(repo, "t-done-first", "done", "2026-11-23 08:00:00")
    _add_task(repo, "t-paused-last", "paused_input", "2026-11-23 08:05:00")

    sessions = {s["session_id"]: s for s in repo.list_sessions(1)}

    assert sessions["s-1"]["has_pending_input"] is True


# --------------------------------------------------------------------------- #
# 3. 「跳过」落库
# --------------------------------------------------------------------------- #

def test_skip_action_supersedes_and_is_idempotent_after(repo, client):
    _add_task(repo, "t-skip", "paused_input", "2026-11-23 08:00:00")

    res = client.post(
        "/api/v1/tasks/t-skip/answer", json={"action": "skip"}, headers={"Authorization": f"Bearer {_token()}"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "superseded"
    assert repo.get_task("t-skip")["status"] == "superseded"

    again = client.post(
        "/api/v1/tasks/t-skip/answer", json={"action": "skip"}, headers={"Authorization": f"Bearer {_token()}"}
    )
    assert again.status_code == 409  # 已不是 paused_input，不许再作废一次


# --------------------------------------------------------------------------- #
# 4. 流式心跳
# --------------------------------------------------------------------------- #

def test_heartbeat_emits_until_stopped(monkeypatch):
    from app.api.routes import _start_heartbeat

    monkeypatch.setattr(settings, "heartbeat_interval_seconds", 0.05)
    q: queue.Queue = queue.Queue()
    stop = threading.Event()

    _start_heartbeat(q, "run-hb", stop)
    first = q.get(timeout=2)
    stop.set()

    assert first.type == EventType.HEARTBEAT
    assert first.data["elapsed_s"] >= 1
    # seq 从 10^6 起：不与 run 自身事件抢号，前端按 seq 排序不会被打乱
    assert first.seq >= 10**6

    # 停表后不再产出（多等几个周期确认线程已退出）
    import time as _t

    _t.sleep(0.2)
    leftovers = []
    while not q.empty():
        leftovers.append(q.get())
    assert leftovers == []
