"""LangGraph 编排骨架测试（p3.1）：路由真正驱动控制流 + NDJSON 事件单调有序。"""
from fastapi.testclient import TestClient

from app.core.events import EventType, parse_line
from app.main import app
from app.orchestration.graph import run_task


def test_simple_input_routes_single():
    result, events = run_task("帮我查一下上个季度的销售汇总")
    assert result["route"] == "single"
    types = [e.type for e in events]
    assert EventType.STATUS in types
    assert types[-1] == EventType.DONE
    # seq 单调不重复（跨节点共享 emitter）
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert {e.run_id for e in events} == {result["run_id"]}


def test_complex_input_routes_multi():
    result, events = run_task("先分析销售数据，然后基于分析结果生成报表，同时导出 excel 和 pdf")
    assert result["route"] == "multi"
    assert any(
        e.type == EventType.STATUS and e.data.get("agent") == "orchestrator" for e in events
    )
    # p3.2：复杂任务带子任务 DAG
    dag = result["dag"]
    assert dag and len(dag["subtasks"]) >= 2
    assert dag["topo_order"]  # 拓扑序非空


def test_events_roundtrip_through_ndjson():
    _result, events = run_task("画一个柱状图看板")
    for ev in events:
        assert parse_line(__import__("json").dumps(ev.model_dump(mode="json"))) is not None


def test_tasks_endpoint_streams_ndjson(monkeypatch):
    # 真实 HTTP 层回归：/tasks 必须逐行吐出 NDJSON（曾漏 import encode_line 被实跑抓到）
    # p6.2c：/tasks 强制登录身份（落库需要 user.id）——这里自签 token + sqlite 内存库
    import jwt as pyjwt
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool

    from app.core.config import settings

    monkeypatch.setattr(settings, "jwt_secret", "test-secret-p62c")
    eng = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with eng.begin() as c:
        c.execute(text("CREATE TABLE user (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, trace TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        # p6.4：token 池真账——/tasks 现在按登录身份 reserve/settle
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO user (id, employee_id, username, role) VALUES (1,'EMP001','dev','admin')"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, 100000)"))
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: eng)

    token = pyjwt.encode({"sub": "EMP001"}, "test-secret-p62c", algorithm="HS256")
    c = TestClient(app)
    r = c.post(
        "/api/v1/tasks",
        json={"text": "先清洗，再分析，再出报表"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert "ndjson" in r.headers["content-type"]
    events = [parse_line(l) for l in r.text.splitlines() if l.strip()]
    assert events and events[-1].type == EventType.DONE
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
