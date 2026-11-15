"""Phase E 评测门禁（v2.2.0-p1.12）：golden set 全量用例在编排层必须通过。

工具真执行（sqlite 环境，订单表缺失 → 工具失败属预期——评测断言的是编排行为：
route / 工具选择 / 任务级无死信，不断言工具结果）。
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from evals.eval_core import load_cases, run_case


@pytest.fixture(scope="module")
def eval_engine():
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with eng.begin() as c:
        for ddl in (
            "CREATE TABLE user (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0)",
            "CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT)",
            "CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, pause_reason TEXT, pause_payload TEXT, retry_of TEXT, request_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, trace TEXT)",
            "CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)",
            "CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, kind TEXT DEFAULT 'task', created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE runtime_setting (setting_key TEXT PRIMARY KEY, setting_value TEXT)",
        ):
            c.execute(text(ddl))
    return eng


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_golden_case(eval_engine, monkeypatch, case):
    from app.core import runtime_settings
    from app.core.config import settings

    monkeypatch.setattr("app.core.db.get_engine", lambda: eval_engine)
    monkeypatch.setattr(runtime_settings, "_loaded", False)
    monkeypatch.setattr(runtime_settings, "_values", {})
    monkeypatch.setattr(settings, "llm_gateway_url", "")
    # 覆盖 conftest 的 _no_real_llm：评测走 EvalAdapter（不真联网），但 brain 需要
    # key 检查通过才会用 LlmBrain（否则回落 StubBrain 不调工具，评测失去意义）
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-eval-dummy")

    res = run_case(case, engine=eval_engine)
    assert res.ok, f"{res.case_id} 失败：{res.failures}（route={res.route} tools={res.tools_called} status={res.status}）"

