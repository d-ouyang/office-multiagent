"""子任务 DAG 拆分（p3.2）——设计文档 §四.2 第三步：复杂任务拆成子任务 DAG + 依赖关系。

纪律：与 p3.1 一致，用【配置驱动的确定性规则】打底——按检测到的意图，依 planner.yaml
的 `dag.dependencies` 生成子任务与依赖边；被依赖意图不在本次任务里则忽略该边。
LLM 分解（规则表达不了的长尾 / 歧义）留作 DecisionModel 插槽（p3.1 已埋接口）。
DAG 只负责「拆 + 定依赖 + 拓扑序」，真实调度执行在 Phase 4 Orchestrator。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .planner import Plan, load_planner_config


@dataclass
class Subtask:
    id: str
    agent_type: str
    intent: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending / running / done / failed


@dataclass
class DAG:
    subtasks: list[Subtask]

    def by_id(self) -> dict[str, Subtask]:
        return {s.id: s for s in self.subtasks}

    def topo_order(self) -> list[Subtask]:
        """Kahn 拓扑排序；有环抛 ValueError（配置写错立刻炸，fail-fast）。"""
        ids = [s.id for s in self.subtasks]
        indeg = {i: 0 for i in ids}
        adj: dict[str, list[str]] = {i: [] for i in ids}
        for s in self.subtasks:
            for dep in s.depends_on:
                adj[dep].append(s.id)
                indeg[s.id] += 1
        queue = sorted(i for i in ids if indeg[i] == 0)
        byid = self.by_id()
        order: list[Subtask] = []
        while queue:
            n = queue.pop(0)
            order.append(byid[n])
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
            queue.sort()
        if len(order) != len(ids):
            raise ValueError("DAG 存在环，无法拓扑排序")
        return order

    def to_dict(self) -> dict:
        return {
            "subtasks": [
                {
                    "id": s.id,
                    "agent_type": s.agent_type,
                    "intent": s.intent,
                    "depends_on": s.depends_on,
                    "status": s.status,
                }
                for s in self.subtasks
            ],
            "topo_order": [s.id for s in self.topo_order()],
        }


def decompose(plan: Plan) -> DAG:
    """把一个（复杂）任务的 Plan 拆成子任务 DAG。"""
    cfg = load_planner_config()
    intents_cfg = cfg.get("intents", {})
    deps_cfg = cfg.get("dag", {}).get("dependencies", {})
    present = set(plan.intents)
    subtasks: list[Subtask] = []
    for intent in plan.intents:  # 主意图在前，保持可读顺序
        agent = intents_cfg.get(intent, {}).get("agent", "general")
        deps = [d for d in deps_cfg.get(intent, []) if d in present]
        subtasks.append(Subtask(id=intent, agent_type=agent, intent=intent, depends_on=deps))
    dag = DAG(subtasks=subtasks)
    dag.topo_order()  # 触发环校验
    return dag
