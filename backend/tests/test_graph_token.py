"""Token 配额中断 + 断点续跑测试（p4.2，§十四.3：余额不足→paused_insufficient_quota→充值后续跑）。"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.events import EventType, RunEventEmitter
from app.core.token_pool import TokenPool
from app.orchestration.graph import build_graph, run_task


def _pool(balance: int) -> tuple[TokenPool, object]:
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(
            text(
                "CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, "
                "kind TEXT DEFAULT 'task', note TEXT, amount INTEGER, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        c.execute(text("INSERT INTO wallet (user_id, balance) VALUES (1, :b)"), {"b": balance})
    return TokenPool(eng), eng


def test_quota_interrupt_then_resume_completes():
    tp, eng = _pool(50)  # 余额 50 < estimate 100
    em = RunEventEmitter("r", "t")
    events: list = []
    cp = MemorySaver()
    graph = build_graph(em, events.append, token_pool=tp, checkpointer=cp)
    cfg = {"configurable": {"thread_id": "t1"}}
    init = {
        "text": "先查一下制度，然后基于制度分析销售数据",
        "run_id": "r",
        "turn_id": "t",
        "user_id": 1,
        "estimate": 100,
    }
    state = graph.invoke(init, cfg)
    assert "__interrupt__" in state  # 余额不足 → 暂停
    assert tp.balance(1) == 50  # 预扣失败，未扣

    with eng.begin() as c:  # 充值
        c.execute(text("UPDATE wallet SET balance = balance + 1000 WHERE user_id=1"))
    state2 = graph.invoke(Command(resume=True), cfg)  # 续跑
    assert state2.get("route") == "multi"  # 跑完
    assert tp.balance(1) == 950  # 50 + 1000 - 100


def test_run_task_paused_emits_quota_event():
    tp, _ = _pool(10)
    result, events = run_task("查一下制度", user_id=1, estimate=100, token_pool=tp)
    assert result["status"] == "paused_insufficient_quota"
    assert any(e.type == EventType.QUOTA_PAUSED for e in events)
    assert events[-1].type == EventType.DONE
    assert tp.balance(1) == 10  # 未扣


def test_run_task_sufficient_settles_full_refund():
    tp, _ = _pool(1000)
    result, events = run_task("查一下制度", user_id=1, estimate=100, token_pool=tp)
    assert result["status"] == "done"
    assert result["route"] == "single"
    assert tp.balance(1) == 1000  # reserve 100 后 settle actual=0 全额退回


# --------------------------------------------------------------------------- #
# p4.3c：multi 路由 token 汇总（此前 multi_node 不返回 tokens_used → settle 全额退回，
# 多 Agent 真实消耗不计账，§十四 对账恒等式破洞）
# --------------------------------------------------------------------------- #

class _FakeUsageBrain:
    """带 usage 的假脑（每子任务 7 token）：验证 multi 汇总与落账。"""

    def __init__(self, *args, **kwargs) -> None:
        self.usage = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7, "calls": 1}

    def next_step(self, task, history):
        from app.orchestration.react import Step

        return Step(thought="t", final="done")


def test_multi_route_aggregates_subtask_tokens(monkeypatch):
    monkeypatch.setattr("app.orchestration.graph.make_brain", lambda *a, **k: _FakeUsageBrain())
    result, _events = run_task("先查一下制度，然后基于制度分析销售数据")
    assert result["route"] == "multi"
    n = len(result["dag"]["subtasks"])
    assert n >= 2
    # p6.30：汇总脑也是一次真 LLM 调用，用量入账 → 子任务 n 个 + 汇总 1 次
    assert result["tokens_used"] == 7 * (n + 1)


def test_multi_route_settles_actual_usage(monkeypatch):
    # 真账：reserve 100 → settle actual=21 → 净扣 21；ledger 两行配对如实记录
    tp, _ = _pool(1000)
    monkeypatch.setattr("app.orchestration.graph.make_brain", lambda *a, **k: _FakeUsageBrain())
    result, _events = run_task(
        "先查一下制度，然后基于制度分析销售数据",
        user_id=1,
        estimate=100,
        token_pool=tp,
    )
    assert result["status"] == "done"
    assert result["route"] == "multi"
    n = len(result["dag"]["subtasks"])
    assert tp.balance(1) == 1000 - 7 * (n + 1)
    settle_rows = [r for r in tp.recent(1, limit=10) if r["settle"] is not None]
    assert len(settle_rows) == 1
    assert settle_rows[0]["reserve"] == 100 and settle_rows[0]["settle"] == 7 * (n + 1)


def test_multi_route_stub_baseline_settles_zero(monkeypatch):
    # StubBrain 无 usage → 汇总 0 → 全额退回（与 single 基线一致，回归不变）
    tp, _ = _pool(1000)
    result, _events = run_task(
        "先查一下制度，然后基于制度分析销售数据",
        user_id=1,
        estimate=100,
        token_pool=tp,
    )
    assert result["route"] == "multi"
    assert result["tokens_used"] == 0
    assert tp.balance(1) == 1000


def test_dag_max_concurrency_config_default():
    from app.core.config import settings

    assert settings.dag_max_concurrency == 3  # p4.3c：默认 3，1=串行回落
