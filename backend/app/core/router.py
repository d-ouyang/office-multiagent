"""路由器（p3.1）——设计文档 §四.3：简单 → 单 Agent ReAct 直跑；复杂 → Orchestrator 多 Agent。

依据 Planner 的复杂度分与阈值（planner.yaml 的 complexity.complexity_threshold）决策。
Orchestrator / ReAct 的具体实现在 Phase 4，本模块只产出【路由决策】。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .planner import Plan, load_planner_config, plan as run_plan


@dataclass
class RouteDecision:
    mode: str                       # 'single' | 'multi'
    reason: str
    score: float
    threshold: float
    primary_agent: str              # 主意图对应的 Agent 类型（办公能力池）
    intents: list[str] = field(default_factory=list)


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
