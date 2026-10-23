"""Orchestrator 调度（p4.1）——设计文档 §四.3/§六：按 DAG 拓扑分层执行，层内互不依赖（可并行），
层间有依赖；各子任务跑单 Agent ReAct，最后汇总。基线层内串行（确定性、可测），
并行化（asyncio.gather）留作后续，接口已按"层"组织好。

p4.3a：上游结果传递给下游——`run_dag` 把已完成的直接上游 `AgentResult` 交给
`agent_runner(subtask, upstream)`，`compose_subtask_text` 负责拼进子任务文本
（摘要 + 截断 + 上游失败如实标注，遵循 observation 摘要化纪律）。
"""
from __future__ import annotations

from collections.abc import Callable

from ..core.decomposer import DAG, Subtask
from ..core.events import Event, RunEventEmitter
from .react import AgentResult, StubBrain, run_react
from .tools import ToolRegistry

#: 单个上游结果进下游任务文本的截断上限（p6.7/p6.9 教训：进 LLM 上下文必须摘要化）
UPSTREAM_MAX_CHARS = 2000


def compose_subtask_text(
    intent: str,
    upstream: dict[str, AgentResult] | None,
    *,
    max_chars_per_upstream: int = UPSTREAM_MAX_CHARS,
) -> str:
    """拼子任务文本：intent + 上游结果摘要（p4.3a）。

    - 无上游 → 只给 intent 任务（与 p4.1 行为一致，向后兼容）。
    - 上游成功 → final 截断到 `max_chars_per_upstream`，超长如实标注已截断。
    - 上游 `hit_cap`（未完成/强制收尾）→ 标注「未完成」，并明确提示不要当作
      已完成的数据（§四.5：失败不可伪装成结果）。
    """
    if not upstream:
        return f"{intent} 任务"
    blocks: list[str] = []
    for dep_id, res in upstream.items():
        final = res.final or ""
        tail = ""
        if len(final) > max_chars_per_upstream:
            final = final[:max_chars_per_upstream]
            tail = "……（上游结果已截断）"
        if res.hit_cap:
            blocks.append(
                f"- 【{dep_id}】未完成（{res.iterations} 步后强制收尾）：{final}{tail}。"
                "这是未完成的上游产出，不要当作已完成的数据，缺的部分如实说明。"
            )
        else:
            blocks.append(f"- 【{dep_id}】{final}{tail}")
    return (
        f"{intent} 任务\n\n"
        "【上游子任务结果】（来自依赖步骤，可直接引用）\n"
        + "\n".join(blocks)
        + "\n\n请基于上述上游结果完成本任务；上游未完成时如实说明缺什么，不要编造上游数据。"
    )


def topo_levels(dag: DAG) -> list[list[Subtask]]:
    """把 DAG 分成拓扑层：同层子任务依赖都已满足（可并行），按层推进。有环抛错。"""
    done: set[str] = set()
    remaining = {s.id: s for s in dag.subtasks}
    levels: list[list[Subtask]] = []
    while remaining:
        layer = [s for s in remaining.values() if all(d in done for d in s.depends_on)]
        if not layer:
            raise ValueError("DAG 存在环，无法分层调度")
        levels.append(layer)
        for s in layer:
            done.add(s.id)
            del remaining[s.id]
    return levels


def run_dag(
    dag: DAG,
    *,
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
    agent_runner: Callable[[Subtask, dict[str, AgentResult]], AgentResult],
) -> dict[str, AgentResult]:
    """按拓扑层执行各子任务（层内串行基线），返回 {subtask_id: AgentResult}。

    p4.3a：`agent_runner(subtask, upstream)`——upstream 是该子任务已完成的直接上游
    结果（按 depends_on 过滤，无依赖传空 dict）；下游据此接上一步的产出。
    """
    results: dict[str, AgentResult] = {}
    for level in topo_levels(dag):
        for st in level:
            emit(emitter.status(st.agent_type, "running", subtask_id=st.id))
            upstream = {dep: results[dep] for dep in st.depends_on if dep in results}
            results[st.id] = agent_runner(st, upstream)
            emit(emitter.status(st.agent_type, "done", subtask_id=st.id))
    return results


def default_agent_runner(
    tools: ToolRegistry | None = None,
) -> Callable[[Subtask, dict[str, AgentResult]], AgentResult]:
    """默认子任务执行器：用 StubBrain 跑一步 ReAct（无 LLM，闭环跑通用）。

    p4.3a：接住 upstream 参数并拼进任务文本（与 graph 的 spec_agent_runner 同构）。
    """

    reg = tools if tools is not None else ToolRegistry()

    def _run(st: Subtask, upstream: dict[str, AgentResult] | None = None) -> AgentResult:
        em = RunEventEmitter("sub", st.id)
        return run_react(
            compose_subtask_text(st.intent, upstream or {}),
            StubBrain(f"[{st.agent_type}] 完成 {st.intent}"),
            reg,
            emitter=em,
        )

    return _run
