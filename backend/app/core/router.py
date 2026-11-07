"""路由器（p3.1）——设计文档 §四.3：简单 → 单 Agent ReAct 直跑；复杂 → Orchestrator 多 Agent。

依据 Planner 的复杂度分与阈值（planner.yaml 的 complexity.complexity_threshold）决策。
Orchestrator / ReAct 的具体实现在 Phase 4，本模块只产出【路由决策】。
p5.6 起叠加廉价预检（capability_guards）：single 主意图 Agent 的工具池不覆盖问句
强实体词所需工具时，改道 general 兜底——路由只决定「从哪开始」，不决定「能做什么」。
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .planner import Plan, load_planner_config, plan as run_plan


@dataclass
class RouteDecision:
    mode: str                       # 'single' | 'multi'
    reason: str
    score: float
    threshold: float
    primary_agent: str              # 主意图对应的 Agent 类型（办公能力池）
    intents: list[str] = field(default_factory=list)


@functools.lru_cache(maxsize=1)
def _agent_tool_pools() -> dict[str, set[str]]:
    """agent_type → 工具集合（读 agents.yaml，供 p5.6 能力预检）。"""
    import yaml  # 懒导入，与 planner 一致

    p: Path | None = None
    if settings.agents_config:
        candidate = Path(settings.agents_config)
        p = candidate if candidate.exists() else None
    if p is None:
        candidates = [
            Path("/app/config/agents.yaml"),
            Path(__file__).resolve().parents[2] / "config" / "agents.yaml",
        ]
        p = next((c for c in candidates if c.exists()), None)
    if p is None:
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    pools: dict[str, set[str]] = {}
    for agent_type, item in (raw.get("agents") or {}).items():
        item = item or {}
        pools[str(agent_type)] = {str(t) for t in (item.get("tools") or [])}
    return pools


def _capability_reroute(text: str, primary_agent: str, cfg: dict) -> str | None:
    """p5.6 廉价预检：返回改道目标（general）或 None（不干预）。

    只拦「自信地错」：问句含强实体词、而 single 主意图 Agent 的工具池
    恰好缺该实体所需的工具。agents.yaml 缺失时跳过预检（不因配置缺失放大影响）。
    """
    if primary_agent == "general":
        return None
    pools = _agent_tool_pools()
    if not pools:
        return None
    tools = pools.get(primary_agent)
    if tools is None:
        return "general"
    for entity, required_tool in (cfg.get("capability_guards") or {}).items():
        if str(entity) in text and str(required_tool) not in tools:
            return "general"
    return None


def decide(plan: Plan) -> RouteDecision:
    cfg = load_planner_config()
    threshold = float(cfg.get("complexity", {}).get("complexity_threshold", 3.0))
    intents_cfg = cfg.get("intents", {})
    primary = plan.intents[0] if plan.intents else "general"
    primary_agent = intents_cfg.get(primary, {}).get("agent", "general")
    requested = set(plan.intents)
    covered = set((cfg.get("single_agent_covers", {}) or {}).get(primary, [primary]))
    one_agent_covers = bool(requested) and requested.issubset(covered)
    recommended = str((plan.entities or {}).get("decision_mode") or "")
    if one_agent_covers:
        mode = "single"
        reason = f"主意图 {primary} 的 Agent 已覆盖 {sorted(requested)}，保持单 Agent 顺序完成"
    elif recommended == "single":
        mode = "single"
        reason = f"决策模型建议单 Agent：{plan.entities.get('decision_reason') or '无需跨能力交接'}"
    elif recommended == "multi":
        mode = "multi"
        reason = f"决策模型确认存在跨能力交接：{plan.entities.get('decision_reason') or '需要多 Agent'}"
    elif plan.score >= threshold:
        mode = "multi"
        reason = f"复杂度分 {plan.score} ≥ 阈值 {threshold}，交 Orchestrator 多 Agent 协作"
    else:
        mode = "single"
        reason = f"复杂度分 {plan.score} < 阈值 {threshold}，单 Agent ReAct 直跑"
    if mode == "single":
        # p5.6：multi 不预检——DAG 按意图分派各自专家 Agent，天然无工具错配。
        reroute = _capability_reroute(plan.text, primary_agent, cfg)
        if reroute:
            reason += "；能力预检：问句实体所需工具不在该 Agent 工具池，改道 general 兜底"
            primary_agent = reroute
    return RouteDecision(
        mode=mode,
        reason=reason,
        score=plan.score,
        threshold=threshold,
        primary_agent=primary_agent,
        intents=plan.intents,
    )


def plan_and_route(text: str) -> tuple[Plan, RouteDecision]:
    p = run_plan(text)
    return p, decide(p)
