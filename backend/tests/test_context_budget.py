"""v2.3.0-p1.1：上下文预算器测试（B-1 ~ B-10）。

覆盖：最近优先 / 整块降级 / 半句禁忌 / 0=不限回退 / 丢弃记账 / 末步保底 /
集成不超预算 / 事件字段 / 预算口径修正 / seed 免疫。
"""
from app.core.events import RunEventEmitter
from app.core.token_budget import TaskTokenBudget
from app.orchestration.brain import LlmBrain
from app.orchestration.context_budget import budget_steps
from app.orchestration.memory import estimate_tokens
from app.orchestration.react import Step


def _step(i: int, chars: int, *, action: str | None = "query_orders") -> Step:
    body = ("行数据;\n" * 3) + "字" * chars  # 固定 4 行，便于断言"返回 N 行"
    return Step(
        thought=f"第{i}步",
        action=action,
        action_input={"month": i},
        observation=body,
    )


def _steps(n: int, chars: int) -> list[Step]:
    return [_step(i, chars) for i in range(1, n + 1)]


def test_budget_keeps_recent_steps():
    """B-1：预算紧张时保留最近的步骤（原文），前面的降级。"""
    steps = _steps(6, 3000)
    res = budget_steps(steps, max_tokens=3000)
    assert res.kept >= 1
    assert 6 in res.obs_text                 # 最后一步在
    assert res.obs_text[6].startswith("行数据")  # 是原文（可能被截断），不是降级文案
    assert res.downgraded >= 4


def test_budget_downgrades_old_steps_with_digest():
    """B-2：降级行必须带工具名、参数个数、返回行数——不能只写"已省略"。"""
    steps = _steps(4, 3000)
    res = budget_steps(steps, max_tokens=800)
    digests = [line for line in res.lines if "调用了" in line]
    assert digests, res.lines
    assert "调用了 query_orders，1 个参数，返回 4 行" in digests[0]
    assert "原文" in digests[0]  # 如实标注被压掉多少字


def test_budget_never_splits_a_step():
    """B-3：行数守恒——每步一整块，不出现"半句"。"""
    res = budget_steps(_steps(6, 3000), max_tokens=2500)
    body_lines = [line for line in res.lines if not line.startswith("（更早")]
    assert len(body_lines) == res.kept + res.downgraded
    assert len(body_lines) <= 6


def test_budget_zero_means_unlimited():
    """B-4：预算 0 = 不限，行为回到 p1.0 的逐条截断（回退路径）。"""
    steps = _steps(3, 3000)
    text = LlmBrain._render_history(steps, 24000, 0)
    assert "调用了 query_orders，1 个参数" not in text  # 没有降级
    assert "…（已截断）" not in text                    # 3000 字没到单步上限
    assert text.count("字") == 9000                     # 三步原文全在


def test_budget_reports_dropped():
    """B-5：降级/截断丢了多少字要能报出来（用于事件与巡检）。"""
    res = budget_steps(_steps(6, 3000), max_tokens=3000)
    assert res.dropped_chars > 0
    assert res.truncated is True
    assert res.summary_note()  # 有可读说明


def test_single_step_over_budget_keeps_last():
    """B-6：只有一步且自身超预算 → 保底保留并标注超长截断。"""
    res = budget_steps([_step(1, 50000)], max_tokens=2000)
    assert res.kept == 1
    assert len(res.lines) == 1
    assert "超长截断" in res.lines[0]
    assert estimate_tokens(res.lines[0]) <= 2200  # 允许标签开销的少量溢出


def test_render_history_under_budget_integration():
    """B-7：6 步 × 3 万字文档，渲染后 token 必须落在预算内（M2 的直接证明）。"""
    budget = 20000
    steps = _steps(6, 30000)
    text = LlmBrain._render_history(steps, 24000, budget)
    assert estimate_tokens(text) <= budget
    assert "调用了" in text  # 旧步确实被降级了
    assert "字" * 100 in text  # 最近一步的正文仍然在


def test_context_usage_event_carries_budget():
    """B-8：context_usage 带 budget/dropped/notes，老字段（window/used/items）不变。"""
    em = RunEventEmitter("run1", "turn1")
    ev = em.context_usage(128000, 5000, [{"key": "system"}], budget=76800, dropped=1200)
    assert ev.data["window"] == 128000
    assert ev.data["used"] == 5000
    assert ev.data["items"] == [{"key": "system"}]
    assert ev.data["budget"] == 76800
    assert ev.data["dropped"] == 1200


def test_prompt_upper_bound_not_inflated_for_cjk():
    """B-9：prompt 上界改按 token 估算——2 万字文档不再被算成 6 万而误触任务上限。"""
    msgs = [{"role": "user", "content": "字" * 20000}]
    bound = TaskTokenBudget.prompt_upper_bound(msgs)
    assert 20000 <= bound < 30000  # 旧口径（UTF-8 字节）会是 60000+


def test_seed_step_survives_tiny_budget():
    """B-10：HITL 用户补充输入不可再生——预算再紧也不被省略。"""
    steps = [
        _step(1, 3000),
        Step(thought="", action=None, action_input={}, observation="用户已补充输入：只看华东"),
        _step(3, 3000),
    ]
    res = budget_steps(steps, max_tokens=800)
    assert any("用户已补充输入" in line for line in res.lines)
