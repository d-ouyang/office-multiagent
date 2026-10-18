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
                "user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER)"
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
        "text": "先清洗，再分析，再出报表",
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
