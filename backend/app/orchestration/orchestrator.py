"""Orchestrator 调度（p4.1）——设计文档 §四.3/§六：按 DAG 拓扑分层执行，层内互不依赖（可并行），
层间有依赖；各子任务跑单 Agent ReAct，最后汇总。基线层内串行（确定性、可测），
并行化（asyncio.gather）留作后续，接口已按"层"组织好。

p4.3a：上游结果传递给下游——`run_dag` 把已完成的直接上游 `AgentResult` 交给
`agent_runner(subtask, upstream)`，`compose_subtask_text` 负责拼进子任务文本
（摘要 + 截断 + 上游失败如实标注，遵循 observation 摘要化纪律）。

p4.3b：层内并行落地——同层无依赖子任务用 ThreadPoolExecutor 并行（ReAct 是同步
函数，走线程池而非裸 asyncio.gather）；`max_concurrency<=1` 或单任务层回落串行
基线（确定性可测）。事件 seq 由 EventSequence 加锁保证并发下不重复（events.py）。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..core.decomposer import DAG, Subtask
from ..core.events import Event, RunEventEmitter
from ..core.runs import RunCancelled
from .react import AgentResult, StubBrain, run_react
from .tools import ToolRegistry

logger = logging.getLogger(__name__)

#: 单个上游结果进下游任务文本的截断上限（p6.7/p6.9 教训：进 LLM 上下文必须摘要化）
UPSTREAM_MAX_CHARS = 2000

#: 用户原始请求进子任务文本的截断上限（多意图任务最多 3 个子任务，避免 ×3 膨胀）
REQUEST_MAX_CHARS = 6000

#: 层内默认最大并行子任务数（防 LLM 渠道限流；planner.yaml max_intents=3 天然上限也就 3）
DEFAULT_MAX_CONCURRENCY = 3


def compose_subtask_text(
    intent: str,
    upstream: dict[str, AgentResult] | None,
    *,
    request_text: str = "",
    max_chars_per_upstream: int = UPSTREAM_MAX_CHARS,
) -> str:
    """拼子任务文本：用户请求 + 本步分工 + 上游结果摘要（p4.3a/p4.3d）。

    - 无 request_text 且无上游 → 只给 intent 任务（p4.1 基线，向后兼容）。
    - 有 request_text → 带上用户完整请求并限定本步分工。**p4.3d 修复**：此前子任务
      只有意图关键词（如"analysis 任务"），模型不知道要分析什么，只能反问——真跑
      冒烟原话「任务描述里只有 analysis 任务四个字」。
    - 上游成功 → final 截断到 `max_chars_per_upstream`，超长如实标注已截断。
    - 上游 `hit_cap`（未完成/强制收尾）→ 标注「未完成」，并明确提示不要当作
      已完成的数据（§四.5：失败不可伪装成结果）。
    """
    req = (request_text or "").strip()
    if not req and not upstream:
        return f"{intent} 任务"
    blocks: list[str] = []
    if req:
        if len(req) > REQUEST_MAX_CHARS:
            req = req[:REQUEST_MAX_CHARS] + "……（请求内容已截断）"
        blocks.append(f"【用户请求】\n{req}")
        blocks.append(
            f"【本步分工】只完成与「{intent}」相关的部分；其他环节由上/下游子任务负责，不要越界重复。"
        )
    blocks.append(f"【本步任务】{intent} 任务")
    if upstream:
        ups: list[str] = []
        for dep_id, res in upstream.items():
            final = res.final or ""
            tail = ""
            if len(final) > max_chars_per_upstream:
                final = final[:max_chars_per_upstream]
                tail = "……（上游结果已截断）"
            if res.hit_cap:
                ups.append(
                    f"- 【{dep_id}】未完成（{res.iterations} 步后强制收尾）：{final}{tail}。"
                    "这是未完成的上游产出，不要当作已完成的数据，缺的部分如实说明。"
                )
            else:
                ups.append(f"- 【{dep_id}】{final}{tail}")
        blocks.append("【上游子任务结果】（来自依赖步骤，可直接引用）\n" + "\n".join(ups))
        # p6.30：上游文件/数据资产（file_name、export_id 等）单独列出——下游画图/嵌图
        # 靠这些 id 引用上游文件，只有文字摘要会让下游"想画图但拿不到数据"。
        asset_lines = [
            f"- [{dep_id}] {a.get('display_name') or a.get('file_name')}：file_name={a['file_name']}"
            + (f"，export_id={a['export_id']}" if a.get("export_id") else "")
            + (f"，png_file={a['png_file']}" if a.get("png_file") else "")
            for dep_id, res in (upstream or {}).items()
            for a in (getattr(res, "assets", None) or [])
        ]
        if asset_lines:
            blocks.append("【上游产物（可直接引用的文件）】\n" + "\n".join(asset_lines))
        blocks.append("请基于上述上游结果完成本任务；上游未完成时如实说明缺什么，不要编造上游数据。")
    return "\n\n".join(blocks)


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


def _upstream_of(st: Subtask, results: dict[str, AgentResult]) -> dict[str, AgentResult]:
    """取该子任务已完成的【直接】上游结果（按 depends_on 过滤）。"""
    return {dep: results[dep] for dep in st.depends_on if dep in results}


def _run_subtask(
    st: Subtask,
    agent_runner: Callable[[Subtask, dict[str, AgentResult]], AgentResult],
    upstream: dict[str, AgentResult],
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
) -> tuple[str, AgentResult]:
    """跑一个子任务并推 running/done 状态（供线程池与串行两条路径共用）。"""
    emit(emitter.status(st.agent_type, "running", subtask_id=st.id))
    res = agent_runner(st, upstream)
    emit(emitter.status(st.agent_type, "done", subtask_id=st.id))
    return st.id, res


def _failed_subtask_result(st: Subtask, exc: Exception) -> AgentResult:
    """p5.2：子任务失败的如实结果——`hit_cap=True` 复用「未完成」语义。

    下游 `compose_subtask_text` 对 `hit_cap` 的分支会标注「未完成」并明确提示不要当作
    已完成的数据（§四.5：失败不可伪装成结果），因此不必新增状态字段，也不会被下游
    误当成正常产出引用。
    """
    return AgentResult(
        final=f"子任务 {st.id}（{st.agent_type}）执行失败：{type(exc).__name__}: {exc}",
        steps=[],
        iterations=0,
        hit_cap=True,
    )


def _run_subtask_guarded(
    st: Subtask,
    agent_runner: Callable[[Subtask, dict[str, AgentResult]], AgentResult],
    upstream: dict[str, AgentResult],
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
) -> tuple[str, AgentResult]:
    """p5.2：单个子任务失败不再拖垮整层——隔离并如实标注，保留同层其他子任务成果。

    此前 `as_completed` 里的 `fut.result()` 直接把子任务异常抛出，同层其余子任务即使
    已经跑完、结果也一并丢弃（多层 DAG 下尤其可惜）。

    `RunCancelled` 必须继续上抛：用户主动暂停不是失败，若被隔离吞成「某个子任务失败」
    就会继续往下跑，违背取消语义（tests/test_pause_resume.py 有对应锚）。
    """
    try:
        return _run_subtask(st, agent_runner, upstream, emitter, emit)
    except RunCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - 隔离是刻意的：失败要可见，但不扩散
        logger.exception("DAG 子任务失败已隔离 subtask=%s agent=%s", st.id, st.agent_type)
        emit(emitter.error(f"子任务 {st.id} 执行失败：{exc}", code="SUBTASK_FAILED"))
        # 收尾状态：_run_subtask 的 done 在 runner 之后，异常时没发出，这里补上，
        # 否则前端该子任务的 Agent 徽章会一直停在 running。
        emit(emitter.status(st.agent_type, "done", subtask_id=st.id))
        return st.id, _failed_subtask_result(st, exc)


def run_dag(
    dag: DAG,
    *,
    emitter: RunEventEmitter,
    emit: Callable[[Event], None],
    agent_runner: Callable[[Subtask, dict[str, AgentResult]], AgentResult],
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, AgentResult]:
    """按拓扑层执行各子任务，返回 {subtask_id: AgentResult}（按 dag.subtasks 顺序，确定性）。

    p4.3a：`agent_runner(subtask, upstream)`——upstream 是该子任务已完成的直接上游
    结果（按 depends_on 过滤，无依赖传空 dict）；下游据此接上一步的产出。

    p4.3b：层内并行——同层子任务无依赖，用 ThreadPoolExecutor 并行跑（ReAct 是同步
    函数，线程池是正确姿势；裸 asyncio.gather 包同步函数不会并行）。层间仍串行，
    依赖顺序不受影响。`max_concurrency<=1` 或层内只有 1 个子任务时走串行基线。

    p7.1：`should_cancel()`——每个子任务开始前检查，命中即抛 RunCancelled（用户暂停）。
    p5.2：单个子任务失败（异常）经 `_run_subtask_guarded` 隔离为 `hit_cap=True` 的失败
    结果，同层其余子任务与后续层继续执行，不再整层中断；失败经 error 事件与 final 文案
    如实可见，下游由 `compose_subtask_text` 的 hit_cap 分支感知「上游未完成」。
    """
    results: dict[str, AgentResult] = {}
    for level in topo_levels(dag):
        if should_cancel is not None and should_cancel():
            raise RunCancelled("用户暂停")
        if len(level) <= 1 or max_concurrency <= 1:
            # 串行基线：单任务层或显式关并行（回落开关，行为与 p4.1 一致）
            for st in level:
                if should_cancel is not None and should_cancel():
                    raise RunCancelled("用户暂停")
                st_id, res = _run_subtask_guarded(st, agent_runner, _upstream_of(st, results), emitter, emit)
                results[st_id] = res
            continue
        # 层内并行：先取好各子任务的上游快照（本层依赖都已满足，results 不再变动）
        upstreams = {st.id: _upstream_of(st, results) for st in level}
        workers = min(len(level), max_concurrency)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dag") as pool:
            futures = [
                pool.submit(_run_subtask_guarded, st, agent_runner, upstreams[st.id], emitter, emit)
                for st in level
            ]
            for fut in as_completed(futures):
                # p5.2：子任务异常已在 _run_subtask_guarded 内隔离为失败结果，
                # 这里不再抛出；只有 RunCancelled（用户暂停）会穿透上抛终止整层。
                st_id, res = fut.result()
                results[st_id] = res
    # 并行完成顺序不固定 → 按 dag.subtasks 顺序重建，保证汇总文本确定（可对账）
    return {st.id: results[st.id] for st in dag.subtasks}


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
