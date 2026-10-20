"""单 Agent ReAct 循环（p4.1）——设计文档 §四.4：Thought → Action → Observation 至终答，
max_iterations 防跑飞，超限强制给阶段结论。Brain 可插拔（确定性基线 / 未来 LLM，§12.5 接口化）。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.events import Event, RunEventEmitter
from .tools import ToolRegistry, ToolResult


@dataclass
class Step:
    thought: str = ""
    action: str | None = None       # 工具名；None 表示本步直接给终答
    action_input: dict[str, Any] = field(default_factory=dict)
    observation: str | None = None
    final: str | None = None        # 非 None = 终答，循环结束
    streamed: bool = False          # p6.3：终答已由 brain 逐字推过（run_react 不重复整段发）


class Brain(Protocol):
    """决策脑：给定任务与历史，产出下一步（调工具 or 给终答）。"""

    def next_step(self, task: str, history: list[Step]) -> Step: ...


@dataclass
class AgentResult:
    final: str
    steps: list[Step]
    iterations: int
    hit_cap: bool = False


class StubBrain:
    """确定性基线 brain：一步"思考 + 终答"，不调 LLM（供闭环跑通与测试）。

    真实 LLM brain（DeepSeek/Qwen，§四.4 的 Thought/Action 生成）后续按 Brain 协议插入。
    """

    def __init__(self, answer: str) -> None:
        self.answer = answer

    def next_step(self, task: str, history: list[Step]) -> Step:
        return Step(thought=f"理解任务：{task[:40]}", final=self.answer)


def run_react(
    task: str,
    brain: Brain,
    tools: ToolRegistry,
    *,
    max_iterations: int = 10,
    emitter: RunEventEmitter | None = None,
    emit: Callable[[Event], None] | None = None,
) -> AgentResult:
    """跑 ReAct 循环；超 max_iterations 强制给阶段结论（§四.4 防跑飞）。"""
    history: list[Step] = []

    def _emit(ev: Event) -> None:
        if emit is not None:
            emit(ev)

    for i in range(1, max_iterations + 1):
        step = brain.next_step(task, history)
        if emitter is not None and step.thought:
            _emit(emitter.thinking_delta(step.thought))

        if step.final is not None:
            # p6.3：brain 已逐字推过（streamed）则只记录，不再整段重发
            if emitter is not None and not step.streamed:
                _emit(emitter.content_delta(step.final))
            history.append(step)
            return AgentResult(final=step.final, steps=history, iterations=i)

        # Action → 工具调用 → Observation
        name = step.action or ""
        if emitter is not None:
            _emit(emitter.tool_call_start(name, name, step.action_input))
        res: ToolResult = tools.call(name, **step.action_input)
        obs = res.output if res.ok else (res.error or "工具调用失败")
        if emitter is not None:
            _emit(emitter.observation(name, str(obs)[:500]))
            _emit(
                emitter.tool_call_end(
                    name, name, success=res.ok, error=None if res.ok else (res.error or "")
                )
            )
        step.observation = str(obs)
        history.append(step)

    # 超限：强制阶段结论（不硬编答案，只如实说明已达上限）
    cap = f"已达 max_iterations={max_iterations}，强制给出阶段结论"
    if emitter is not None:
        _emit(emitter.content_delta(cap))
    return AgentResult(final=cap, steps=history, iterations=max_iterations, hit_cap=True)
