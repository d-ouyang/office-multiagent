"""Token 池两段式扣减测试（p4.2，§十四）。用 SQLite 内存库验证原子语义（同一条 SQL 生产 MySQL 亦成立）。"""
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.token_pool import TokenPool


def _make(balance: int) -> tuple[TokenPool, object]:
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with eng.begin() as c:
        c.execute(
            text(
                "CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"
            )
        )
        c.execute(
            text(
                "CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER NOT NULL, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, "
                "kind TEXT DEFAULT 'task', note TEXT, amount INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        c.execute(
            text("INSERT INTO wallet (user_id, balance) VALUES (1, :b)"), {"b": balance}
        )
    return TokenPool(eng), eng


def test_reserve_deducts():
    tp, _ = _make(1000)
    r = tp.reserve(1, 300)
    assert r.ok and r.balance == 700
    assert tp.balance(1) == 700


def test_reserve_no_overdraw_atomic():
    tp, _ = _make(1000)
    r = tp.reserve(1, 2000)  # 超额 → 拒绝
    assert not r.ok
    assert tp.balance(1) == 1000  # 未扣（原子，WHERE balance>=x 不满足）


def test_settle_refunds_difference():
    tp, _ = _make(1000)
    tp.reserve(1, 100)          # 1000 -> 900
    bal = tp.settle(1, 100, 30)  # 实际只用 30，退 70 -> 900 + 70
    assert bal == 970


def test_ledger_records_reserve_and_settle():
    tp, eng = _make(1000)
    tp.reserve(1, 100, task_id="t1")
    tp.settle(1, 100, 30, task_id="t1")
    with eng.connect() as c:
        n = c.execute(
            text("SELECT COUNT(*) FROM token_ledger WHERE user_id=1 AND task_id='t1'")
        ).scalar()
    assert n == 2


def test_zero_estimate_noop():
    tp, _ = _make(1000)
    r = tp.reserve(1, 0)
    assert r.ok and tp.balance(1) == 1000


def test_settle_floor_prevents_negative_balance():
    """p6.11 回归：actual 远超 reserved 时余额不得穿负（钳 0）。

    复现 p6.9 实测：余额 1000、预扣 1000、实际 3493 → 旧逻辑 balance=0-2493=-2493。
    """
    tp, eng = _make(1000)
    tp.reserve(1, 1000, task_id="t_over")  # 1000 -> 0
    bal = tp.settle(1, 1000, 3493, task_id="t_over")
    assert bal == 0  # 不为负
    assert tp.balance(1) == 0


def test_settle_floor_exact_zero_on_crossing():
    """预扣后余额为正，但超支恰好把余额拉到 0（不越界）。"""
    tp, _ = _make(1000)
    tp.reserve(1, 300)  # 1000 -> 700
    bal = tp.settle(1, 300, 1000)  # refund=-700 -> 700-700=0
    assert bal == 0


def test_settle_floor_keeps_ledger_truth():
    """下限保护只钳余额；ledger 仍如实记录 actual（账务可审计）。"""
    tp, eng = _make(1000)
    tp.reserve(1, 1000, task_id="t_truth")
    tp.settle(1, 1000, 3493, task_id="t_truth")
    with eng.connect() as c:
        row = c.execute(
            text(
                "SELECT reserve, settle FROM token_ledger "
                "WHERE user_id=1 AND task_id='t_truth' ORDER BY id DESC LIMIT 1"
            )
        ).first()
    assert row[0] == 1000 and row[1] == 3493  # 实际用量如实留痕

