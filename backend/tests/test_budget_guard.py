"""B3 三级硬预算测试（v2.2.0-p1.6）：入口 429 短路 / tenant 日预算 / 软告警 / 护栏开关。"""
import jwt as pyjwt  # noqa: F401 - 与 test_graph 同款依赖，保证环境一致
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core import runtime_settings
from app.core.config import settings


@pytest.fixture()
def guard_env(monkeypatch):
    """sqlite 内存库（wallet/ledger/runtime_setting）+ TestClient；返回 (client, token, eng)。"""
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with eng.begin() as c:
        c.execute(text("CREATE TABLE user (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, trace TEXT, feedback TEXT, feedback_tags TEXT, feedback_comment TEXT, feedback_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', note TEXT, amount INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE runtime_setting (setting_key TEXT PRIMARY KEY, setting_value TEXT)"))
        c.execute(text("INSERT INTO user (id, employee_id, username, role) VALUES (1,'EMP001','dev','admin')"))
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, 100000)"))
    monkeypatch.setattr("app.core.db.get_engine", lambda: eng)
    # runtime_settings 进程级缓存重置，让每个用例重读 DB
    monkeypatch.setattr(runtime_settings, "_loaded", False)
    monkeypatch.setattr(runtime_settings, "_values", {})
    monkeypatch.setattr(settings, "token_estimate_default", 500)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-p62c")
    monkeypatch.setattr(settings, "budget_alert_webhook_url", "")  # 缺省不发

    token = pyjwt.encode({"sub": "EMP001"}, "test-secret-p62c", algorithm="HS256")
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    yield client, f"Bearer {token}", eng


def _post(client, auth, text="介绍你自己"):
    return client.post("/api/v1/tasks", json={"text": text}, headers={"Authorization": auth})


def test_balance_insufficient_rejected_at_entry_429(guard_env, monkeypatch):
    """per-user 入口短路：余额 < 预估 → 429（不启动编排、不进 graph）。"""
    client, auth, eng = guard_env
    with eng.begin() as c:
        c.execute(text("UPDATE wallet SET balance=100 WHERE user_id=1"))  # < estimate 500
    r = _post(client, auth)
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "BALANCE_INSUFFICIENT"


def test_tenant_daily_budget_rejected_429(guard_env):
    """per-tenant 日预算：当日结算量达上限 → 429（余额再足也拒绝）。"""
    client, auth, eng = guard_env
    with eng.begin() as c:
        c.execute(text("INSERT INTO runtime_setting VALUES ('tenant_daily_token_budget', '100')"))
        c.execute(text("INSERT INTO token_ledger (user_id, task_id, model, settle) VALUES (1, 't1', 'm', 100)"))
    r = _post(client, auth)
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "TENANT_BUDGET_EXCEEDED"


def test_tenant_daily_budget_off_by_default(guard_env):
    """预算 0（缺省）= 关闭：正常放行（非 429）。"""
    client, auth, _ = guard_env
    r = _post(client, auth)
    assert r.status_code != 429


def test_daily_billed_sums_settle_only_task_kind():
    """daily_billed：只累计当日 kind='task' 的 settle 列。"""
    from app.core.token_pool import TokenPool

    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', note TEXT, amount INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO token_ledger (user_id, task_id, model, settle) VALUES (1,'a','m',300)"))
        c.execute(text("INSERT INTO token_ledger (user_id, task_id, model, settle) VALUES (1,'b','m',200)"))
        c.execute(text("INSERT INTO token_ledger (user_id, task_id, model, settle, kind) VALUES (1,'c','m',999,'recharge')"))
    assert TokenPool(eng).daily_billed() == 500


def test_max_iterations_from_runtime_settings(guard_env):
    """循环护栏开关化：runtime_setting 覆盖生效。"""
    from app.orchestration.graph import _max_iterations

    client, auth, eng = guard_env  # noqa: F841 - fixture 建 runtime_setting 表
    with eng.begin() as c:
        c.execute(text("INSERT INTO runtime_setting VALUES ('agent_max_iterations', '25')"))
        runtime_settings._loaded = False  # fixture 后再插值需重读
        runtime_settings._values.clear()
    assert _max_iterations() == 25


def test_budget_alert_fires_once_per_day(guard_env, monkeypatch):
    """软告警：达比例发一次、当日去重；未配置 url 静默。"""
    from app.core import budget_alert

    sent: list[dict] = []

    class FakeResp:
        status_code = 200

    def fake_post(url, json=None, timeout=None, trust_env=None):
        sent.append(json)
        return FakeResp()

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr(settings, "budget_alert_webhook_url", "http://wh.example/hook")

    budget_alert.fire_budget_alert("k1", {"used": 80, "budget": 100})
    budget_alert.fire_budget_alert("k1", {"used": 90, "budget": 100})  # 当日去重
    import time as _t

    _t.sleep(0.2)  # 后台线程
    assert len(sent) == 1 and sent[0]["kind"] == "k1"


def test_budget_alert_silent_without_url(guard_env, monkeypatch):
    from app.core import budget_alert

    monkeypatch.setattr(settings, "budget_alert_webhook_url", "")
    called = []
    monkeypatch.setattr("httpx.post", lambda *a, **k: called.append(a) or (_ for _ in ()).throw(AssertionError("不应发")))
    budget_alert.fire_budget_alert("k2", {})
    assert called == []
