"""评测核心（v2.2.0-p1.12 / Phase E）——golden set 的执行与断言逻辑。

设计：
  · 用例在 jsonl（evals/golden_set.jsonl），断言维度是【编排行为】而非 LLM 文采：
    route（planner 纯规则，确定性）、tools_called（tool_call_start 事件集合）、
    任务级无 error（死信/异常即失败）；
  · brain 用 FakeModelAdapter 脚本按 expect.tools 生成 action——**工具真执行**
    （连调用方给的 engine）；工具自身失败不判负（rag 外部依赖、sqlite 无订单表
    等——我们测的是"编排选对了工具/路由"，不是工具结果）；
  · 双入口：pytest（tests/test_golden_set.py，CI 门禁）与
    scripts/run_evals.py（CLI，本地真库校准/抽样）。

跑法：调用方负责 engine 注入（run_case 内临时替换 app.core.db.get_engine，
结束恢复）；不注入则用真实环境库（CLI 模式）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GOLDEN_SET = Path(__file__).resolve().parent / "golden_set.jsonl"
_LAST_ADAPTER: Any = None  # 诊断用：最近一次评测的 adapter


@dataclass
class CaseResult:
    case_id: str
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures
    route: str = ""
    tools_called: list[str] = field(default_factory=list)
    status: str = ""

    def fail(self, msg: str) -> None:
        self.failures.append(msg)


class EvalAdapter:
    """评测专用常驻适配器：decision-llm 请求返回不可解析 JSON（决策回落规则）；
    brain 请求按序返回 action（每工具一轮）→ 收尾 final EVAL_DONE。
    不用 FakeModelAdapter（弹出语义：callable 一次性，轮数不可控）。"""

    name = "eval"

    def __init__(self, actions: list[str]) -> None:
        self._actions = list(actions)
        self._final = json.dumps({"thought": "评测完成", "final": "EVAL_DONE"}, ensure_ascii=False)
        self.llm_calls = 0
        self.calls: list[dict[str, Any]] = []

    def chat(self, model_id: str, messages: list[dict[str, str]], **kwargs: Any):
        from app.core.llm import LlmResult

        self.llm_calls += 1
        self.calls.append({"model_id": model_id, "last": str(messages[-1].get("content") or "")[:80]})
        if "decision" in model_id:
            return LlmResult(content='{"unsupported": true}')
        if self._actions:
            return LlmResult(content=self._actions.pop(0))
        return LlmResult(content=self._final)

    def chat_stream(self, model_id: str, messages: list[dict[str, str]], **kwargs: Any):
        return self.chat(model_id, messages, **kwargs)


def fake_script(case: dict[str, Any]) -> list[str]:
    """按 expect.tools 生成 action 序列（每工具一轮，供 EvalAdapter 按序返回）。"""
    actions: list[str] = []
    for tool in case.get("expect", {}).get("tools") or []:
        args = (case.get("tool_args") or {}).get(tool) or {}
        actions.append(json.dumps({"thought": "评测步骤", "action": tool, "action_input": args}, ensure_ascii=False))
    return actions


def run_case(case: dict[str, Any], engine: Any = None) -> CaseResult:
    """跑单个用例并断言。engine=None 时用真实环境库（CLI 模式）。"""
    from app.core import model_adapter
    from app.core.events import EventType
    from app.orchestration.graph import run_task

    res = CaseResult(case_id=str(case.get("id") or "?"))
    expect = case.get("expect") or {}

    adapter = EvalAdapter(fake_script(case))
    global _LAST_ADAPTER
    _LAST_ADAPTER = adapter
    model_adapter.set_adapter(adapter)
    events: list[Any] = []
    try:
        result, evs = run_task(
            str(case["text"]),
            run_id=f"eval-{case.get('id')}",
            sink=events.append,
        )
    except Exception as e:  # noqa: BLE001 - 评测不抛：异常即断言失败明细
        res.fail(f"run_task 异常：{type(e).__name__}: {e}")
        return res
    finally:
        model_adapter.reset_adapter()

    res.status = str((result or {}).get("status") or "")
    res.route = str((result or {}).get("route") or "")
    res.tools_called = [
        str(e.data.get("name") or "") for e in events if e.type == EventType.TOOL_CALL_START
    ]

    if expect.get("route") and res.route != expect["route"]:
        res.fail(f"route 期望 {expect['route']}，实际 {res.route}")
    if res.status != "done":
        res.fail(f"任务应 done，实际 {res.status}")
    want_tools = expect.get("tools") or []
    if sorted(res.tools_called) != sorted(want_tools):
        res.fail(f"tools 期望 {want_tools}，实际 {res.tools_called}")
    if any(e.type == EventType.ERROR for e in events):
        res.fail("出现 error 事件（死信路径）")
    for kw in expect.get("observation_contains") or []:
        if not any(kw in str(e.data) for e in events):
            res.fail(f"观察中未找到关键词：{kw}")

    return res


def load_cases(path: Path | None = None, prefix: str | None = None) -> list[dict[str, Any]]:
    p = path or GOLDEN_SET
    cases = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if prefix:
        cases = [c for c in cases if str(c.get("id") or "").startswith(prefix)]
    return cases
