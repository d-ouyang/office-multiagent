"""C1 幂等键测试（v2.2.0-p1.7）：同 run 重投时副作用工具只执行一次。

判据（PLAN-2.2.0 C1）：同一 run 内 (tool_name, args_hash) 第二次调用直接返回
缓存观察、fn 不执行；不同参数正常执行；resume 重放（guard 重新构造）同样命中。
"""
import json

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.invocation_repo import args_hash, lookup, record
from app.orchestration.react import run_react
from app.orchestration.tools import ToolRegistry


def _eng():
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    # MySQL 的 INSERT IGNORE 在 sqlite 用 OR IGNORE 语义不可移植——repo 层用 MySQL 方言；
    # sqlite 测试只覆盖 lookup/record 正常路径（并发撞键由唯一键在生产兜底）。
    with eng.begin() as c:
        c.execute(text(
            "CREATE TABLE tool_invocation (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "run_id TEXT NOT NULL, tool_name TEXT NOT NULL, args_hash TEXT NOT NULL, "
            "args_preview TEXT, observation TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
            "UNIQUE (run_id, tool_name, args_hash))"
        ))
    return eng


def test_args_hash_is_key_order_independent():
    assert args_hash({"a": 1, "b": 2}) == args_hash({"b": 2, "a": 1})
    assert args_hash({"a": 1}) != args_hash({"a": 2})


def test_lookup_record_roundtrip():
    eng = _eng()
    assert lookup(eng, "r1", "export_orders", {"city": "上海"}) is None
    record(eng, "r1", "export_orders", {"city": "上海"}, "已导出 32 行")
    assert lookup(eng, "r1", "export_orders", {"city": "上海"}) == "已导出 32 行"
    # 不同 run / 不同参数互不命中
    assert lookup(eng, "r2", "export_orders", {"city": "上海"}) is None
    assert lookup(eng, "r1", "export_orders", {"city": "北京"}) is None


def test_missing_table_degrades_silently():
    """表未迁移（旧库）：lookup/record 静默降级，绝不阻断任务。"""
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    assert lookup(eng, "r", "t", {}) is None
    record(eng, "r", "t", {}, "x")  # 不抛


def test_react_same_run_replay_executes_once():
    """判据主用例：同一 run 两轮请求同一工具同参数 → fn 副作用恰好 1 次，第二轮吃缓存。"""
    eng = _eng()
    calls: list[int] = []

    def side_effect(city: str) -> str:
        calls.append(1)
        return f"已导出 {city}"

    reg = ToolRegistry()
    reg.register("export_orders", side_effect)

    def guard(tool_name: str, args: dict):
        from app.orchestration.tools import ToolResult

        cached = lookup(eng, "run-x", tool_name, args)
        return ToolResult(ok=True, output=cached) if cached is not None else None

    def recorder(tool_name: str, args: dict, observation: str) -> None:
        record(eng, "run-x", tool_name, args, observation)

    guard.record = recorder

    script = [
        '{"thought":"查","action":"export_orders","action_input":{"city":"上海"}}',
        '{"thought":"再查一次","action":"export_orders","action_input":{"city":"上海"}}',
        '{"thought":"完成","final":"用缓存里的导出结果作答"}',
    ]
    from app.core import model_adapter
    from app.core.events import RunEventEmitter

    model_adapter.set_adapter(model_adapter.FakeModelAdapter(list(script)))
    try:
        res = run_react("导出上海订单", __import__("app.orchestration.brain", fromlist=["LlmBrain"]).LlmBrain(
            model_id="deepseek-chat", tools=reg
        ), reg, emitter=RunEventEmitter("run-x", "turn-x"), invocation_guard=guard)
    finally:
        model_adapter.reset_adapter()

    assert res.final == "用缓存里的导出结果作答"
    assert len(calls) == 1, f"副作用应只发生 1 次，实际 {len(calls)} 次"
    # 第二轮被 react 的重复提示层接管（把上次观察重新喂给模型）——内含缓存观察。
    # 三层防线：react 重复提示（prior>=1）→ react 硬拦（prior>=2）→ 幂等缓存（执行前）。
    assert "已导出 上海" in res.steps[1].observation


def test_dict_output_cached_and_restored():
    """dict 结果（query_orders 类）：序列化存储、命中还原为 dict（下游类型一致）。"""
    eng = _eng()
    calls: list[int] = []

    def query_tool(q: str) -> dict:
        calls.append(1)
        return {"rows": [["9 月", 32]], "clean_id": "c-1"}

    reg = ToolRegistry()
    reg.register("query_orders", query_tool)

    def guard(tool_name: str, args: dict):
        from app.orchestration.tools import ToolResult

        cached = lookup(eng, "run-d", tool_name, args)
        if cached is not None:
            import json as _json

            return ToolResult(ok=True, output=_json.loads(cached))
        return None

    def recorder(tool_name: str, args: dict, observation: str) -> None:
        record(eng, "run-d", tool_name, args, observation)

    guard.record = recorder

    # 两次 run_react 共享同一 Fake 实例：第一次 2 轮 + 第二次 2 轮 = 4 项
    script = [
        '{"thought":"查","action":"query_orders","action_input":{"q":"总量"}}',
        '{"thought":"完成","final":"总量如下"}',
        '{"thought":"查","action":"query_orders","action_input":{"q":"总量"}}',
        '{"thought":"完成","final":"总量如下（缓存）"}',
    ]
    from app.core import model_adapter
    from app.core.events import RunEventEmitter

    model_adapter.set_adapter(model_adapter.FakeModelAdapter(script))
    try:
        # 第一次：真执行 + 登记（dict 被序列化存储）
        run_react("统计订单", __import__("app.orchestration.brain", fromlist=["LlmBrain"]).LlmBrain(
            model_id="deepseek-chat", tools=reg
        ), reg, emitter=RunEventEmitter("run-d", "t1"), invocation_guard=guard)
        calls.clear()
        # 第二次（模拟重投）：命中缓存 → fn 不执行、output 还原为 dict
        res = run_react("统计订单", __import__("app.orchestration.brain", fromlist=["LlmBrain"]).LlmBrain(
            model_id="deepseek-chat", tools=reg
        ), reg, emitter=RunEventEmitter("run-d", "t2"), invocation_guard=guard)
    finally:
        model_adapter.reset_adapter()

    assert len(calls) == 0, "重投后副作用应为 0（缓存命中，fn 未执行）"
    # observation 入 history 时被摘要化为字符串（既有行为）——缓存内容应可追溯
    assert any("c-1" in str(s.observation) for s in res.steps), "重投轮的观察应来自缓存内容"
