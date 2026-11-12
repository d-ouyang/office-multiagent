"""Policy / StateSnapshot / EvalCase 三契约（v2.2.0-p1.3 / Phase A4）。

六契约收官步（路线文档 §4.1）：ModelAdapter（p1.0）、ToolSpec（p1.1）、
Event（p1.2）已各落自然位置；本文件集中收**后三个**——它们现阶段只立契约，
不迁移实现（判定逻辑仍在 token_pool / token_budget / runtime_settings /
checkpoints / validator / feedback_repo 原地跑），迁移是 Phase B/C/E 的分步动作。

契约与现状的映射（设计时就对着活代码，不是空中楼阁）：
  Policy         ← token_pool（钱包两段式）+ token_budget（run 级预算）+
                    runtime_settings（全员开关）+ DAG 暂停语义
  StateSnapshot  ← checkpoints.py（LangGraph checkpointer）+ runs.py（取消登记）
  EvalCase       ← validator.py（数字对账）+ feedback_repo（点赞点踩流水）
                    ——Phase E1 golden set 的入口结构。

红线：本文件**零运行时副作用**（不 import 上述模块、不连库）——纯 dataclass +
Protocol，测试不起数据库即可覆盖（这是 password_policy 分层经验的重用）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# --------------------------------------------------------------------------- #
# Policy：判定结果的统一形态（收口点 Phase B3 落地时的输出契约）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PolicyDecision:
    """一次治理判定的结果。**allow=False 时其余字段即「该怎么办」**。

    现状映射：quota 暂停=（allow=False, reason="quota", budget_cap=剩余额度）；
    预算暂停=（allow=False, reason="budget", budget_cap=本轮预算余额）——
    两处现在各发各的事件（quota_paused / paused_budget），收口后统一产本结构，
    事件构造器由判定结果驱动（B3）。
    """

    allow: bool
    reason: str = ""            # not allow 时的机器可读原因（quota/budget/rate_limit/hitl）
    budget_cap: int | None = None   # 命中的预算上限（余额/预算余额，供前端提示）
    rate_limit: str | None = None   # 命中的限流规则名（网关侧，B3 接）
    hitl_required: bool = False     # 该操作需人工确认（ask_user 场景，预留）
    degrade_chain: tuple[str, ...] = ()  # 降级链（如 ("ollama", "deepseek")，B1 落）


@runtime_checkable
class PolicyEngine(Protocol):
    """判定引擎契约：输入身份+动作+预算上下文，输出 PolicyDecision。

    Phase B3 收口时：token_pool/token_budget/runtime_settings 的判定
    迁入实现类（或组合成链），业务侧只消费 decision。
    """

    def decide(
        self,
        *,
        user_id: int,
        action: str,
        estimated_cost: int | None = None,
    ) -> PolicyDecision: ...


# --------------------------------------------------------------------------- #
# StateSnapshot：运行状态的规范形态（Phase C2 lease / D1 事件流回放消费）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StateSnapshot:
    """一个 run 的可恢复状态快照。

    现状映射：LangGraph checkpointer 存节点边界 state（本契约的 `state` 字段
    即其序列化形态）；`version` 对应 checkpoint 的 seq（事件流序号）；
    `lease_owner` 预留给 Phase C2（同 run 单执行者，MySQL GET_LOCK 实现，
    Redis 只做缓存/队列的红线不破）。

    恢复语义（C3 的判据基础）：给定 StateSnapshot + 事件流回放（D1），
    任何执行者可从 `state` 续跑；副作用安全由 C1 幂等键保证，
    计算安全由 `version`（≤ version 的步骤不再重算）收窄重跑范围。
    """

    run_id: str
    version: int                      # 单调递增（对齐事件流 seq）
    state: dict[str, Any] = field(default_factory=dict)
    checkpoint_ts: int = 0            # 毫秒时间戳
    lease_owner: str | None = None    # 当前持有者（C2 落地前为 None）


# --------------------------------------------------------------------------- #
# EvalCase：评测用例的统一形态（Phase E1 golden set / 回归门禁的入口结构）
# --------------------------------------------------------------------------- #


@dataclass
class Verdict:
    """一次评测的裁决。pass=False 时 notes 必须给出可定位的失败原因。"""

    passed: bool
    score: float | None = None        # 0~1，连续指标（groundedness 等）；通过/不通过型为 None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "score": self.score, "notes": self.notes}


@dataclass
class EvalCase:
    """一条评测用例：input→expected 对照，retrieved/trace_ref 可选。

    来源映射（E1 回流管道的三个入口）：
    - 人工灰度用例（docs/灰度观察-*.md）→ input/expected 手写；
    - validator 数字对账失败（对不上的终答）→ expected=观察里的数字，
      trace_ref=任务 id；
    - 点踩流水（dislike + tags）→ input=用户原话，expected 空（badcase，
      verdict.passed=False 起）。
    """

    case_id: str
    input: str
    expected: str = ""
    retrieved: str = ""               # RAG 场景的引用上下文（office 侧可空）
    trace_ref: str = ""               # 溯源（任务 id / 会话 id / 事件流 run_id）
    verdict: Verdict | None = None    # None = 未裁决（golden set 里的待跑用例）

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "input": self.input,
            "expected": self.expected,
            "retrieved": self.retrieved,
            "trace_ref": self.trace_ref,
            "verdict": self.verdict.to_dict() if self.verdict else None,
        }
