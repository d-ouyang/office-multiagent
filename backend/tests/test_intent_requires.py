"""v2.4.0-p1.0：意图能力声明（intents.requires）与预检合并测试。

背景：路由预检原本只靠 `capability_guards`（句子里的实体 → 工具），是"说法级"映射，
每加一个工具/换一种说法都要人肉同步。本步加"意图级"声明：每个意图写清它需要哪些工具，
预检时两源合并——配置漂移（改 agents.yaml 漏配）与意图判错（句子里的强实体）各有一道。
"""
import pytest

from app.core import planner, router
from app.core.planner import plan
from app.core.router import decide


@pytest.fixture(autouse=True)
def _fresh_config():
    """planner.yaml / agents.yaml 都是 lru_cache；被 monkeypatch 换成 lambda 时要容错。"""

    def _clear():
        planner.load_planner_config.cache_clear()
        clear = getattr(router._agent_tool_pools, "cache_clear", None)
        if clear is not None:
            clear()

    _clear()
    yield
    _clear()


def _pools_without(agent: str, tool: str) -> dict[str, set[str]]:
    """先取真实工具池再改（不能在 monkeypatch 之后再调原函数，会递归）。"""
    pools = {k: set(v) for k, v in router._agent_tool_pools().items()}
    pools[agent] = pools.get(agent, set()) - {tool}
    return pools


def test_plan_carries_rag_requires():
    """A-1：rag 意图声明 rag_retrieve。"""
    p = plan("差旅报销制度是怎么规定的")
    assert p.intents[:1] == ["rag"]
    assert "rag_retrieve" in p.requires


def test_plan_carries_orders_requires():
    """A-2：orders 意图声明 query_orders（历史事故：订单问句被 rag 劫持）。"""
    p = plan("查一下最近10笔订单")
    assert "query_orders" in p.requires


def test_requires_union_for_multi_intent():
    """A-3：多意图时取并集，保序去重。"""
    p = plan("先查报销制度，再按制度分析订单趋势")
    assert "rag_retrieve" in p.requires
    assert "query_orders" in p.requires
    assert len(p.requires) == len(set(p.requires))


def test_every_intent_requires_covered_by_its_agent():
    """A-4（配置自洽护栏）：每个意图的 requires 必须被它自己的 Agent 工具池覆盖。

    这条是 CI 门槛：以后改 agents.yaml 挪走某个工具、或加意图忘了配 Agent，这里先红。
    """
    cfg = planner.load_planner_config()
    pools = router._agent_tool_pools()
    for name, spec in (cfg.get("intents") or {}).items():
        required = set(spec.get("requires") or [])
        if not required:
            continue
        agent = str(spec.get("agent") or "")
        missing = required - pools.get(agent, set())
        assert not missing, f"意图 {name} 的 requires 未被 {agent} 覆盖，缺 {sorted(missing)}"


def test_missing_tool_reroutes_to_general(monkeypatch):
    """A-5：工具池被改坏（挪走 query_orders）时，订单任务自动改道 general 而不是硬跑。"""
    broken = _pools_without("data_analysis", "query_orders")  # 必须在 patch 之前求值
    monkeypatch.setattr(router, "_agent_tool_pools", lambda: broken)
    d = decide(plan("查一下最近10笔订单"))
    assert d.primary_agent == "general"
    assert "query_orders" in d.reason


def test_covered_agent_not_rerouted():
    """A-6：配置正常时不误伤——订单仍走 data_analysis。"""
    d = decide(plan("查一下最近10笔订单"))
    assert d.primary_agent == "data_analysis"
    assert "改道" not in d.reason


def test_file_reading_still_guarded_by_entity():
    """A-7：实体级 guards 仍生效（requires 表达不了"读文件"这种任务形态）。"""
    d = decide(plan("检索知识库并读取文件 a.md"))
    assert d.primary_agent == "general"
    assert "read_document" in d.reason
