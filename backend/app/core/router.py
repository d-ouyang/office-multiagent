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


def _capability_reroute(plan: Plan, primary_agent: str, cfg: dict) -> tuple[str, set[str]] | None:
    """路由预检：主 Agent 的工具池够不够用。返回 (改道目标, 缺失工具) 或 None。

    两个需求来源（v2.4.0-p1.0，缺一不可）：
      1. `plan.requires`——**意图级**声明（orders 要 query_orders、rag 要 rag_retrieve）。
         防"配置漂移"：以后有人改 agents.yaml 的工具池，漏配会在预检阶段被兜住。
      2. `capability_guards`——**实体级**映射（"订单"→query_orders、"读取文件"→read_document）。
         防"意图判错"：小模型把读文件判成 rag 时，靠句子里的实体把任务拉回有能力的 Agent。

    以前只有第 2 层，等于"用户怎么说"驱动路由；加第 1 层后，"意图需要什么"也参与判定。
    改道目标固定 general——它是唯一持有全量工具的 Agent。
    """
    if primary_agent == "general":
        return None
    pools = _agent_tool_pools()
    if not pools:
        return None  # 配置缺失时跳过预检，不因缺配置放大影响
    tools = pools.get(primary_agent)
    if tools is None:
        return "general", set()
    needed = set(plan.requires)
    for entity, required_tool in (cfg.get("capability_guards") or {}).items():
        if str(entity) in plan.text:
            needed.add(str(required_tool))
    missing = needed - tools
    return ("general", missing) if missing else None


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
        reroute = _capability_reroute(plan, primary_agent, cfg)
        if reroute:
            target, missing = reroute
            detail = f"缺 {sorted(missing)}" if missing else "Agent 未注册"
            reason += f"；能力预检：{detail}，改道 {target} 兜底"
            primary_agent = target
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
