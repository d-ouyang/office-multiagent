"""单 Agent ReAct 循环（p4.1）——设计文档 §四.4：Thought → Action → Observation 至终答，
max_iterations 防跑飞，超限强制给阶段结论。Brain 可插拔（确定性基线 / 未来 LLM，§12.5 接口化）。
"""
from __future__ import annotations

import time
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
    invalid_action: bool = False    # p6.7：action 是无效工具名（LLM 幻觉，如 "none"）
    chunked: bool = False           # p6.7：终答需由 run_react 切片推（JSON 包装的 final）


def _summarize_observation(obs: Any, *, max_chars: int = 24000) -> str:
    """p6.7：工具结果进 LLM 上下文的可读摘要——不是 str(dict) 全文。
    p6.9：content 截断 1200 → 24000（read_document max_chars 同步 50000，
    "通读整篇"场景 2 万字文档全量进上下文；deepseek-chat 128K 装得下）。

    原实现把含 8000 字 content 的 dict repr 原样塞进 history，LLM 下一轮上下文
    被垃圾撑爆（真跑见证：read_document 成功后 LLM 幻觉出 action="none"）。
    现在：dict 取关键字段、content 截断、截断如实标注。
    """
    if isinstance(obs, dict):
        parts = []
        for key in ("file_name", "total_chars", "answer", "route"):
            if key in obs:
                parts.append(f"{key}={obs[key]}")
        content = obs.get("content")
        if isinstance(content, str):
            shown = content[:max_chars]
            tail = f"…（原文共 {obs.get('total_chars', len(content))} 字，已截断展示）" if len(content) > max_chars else ""
            parts.append(f"content={shown}{tail}")
        if "sources" in obs:
            parts.append(f"sources={obs['sources']}")
        text = "；".join(parts)
    else:
        text = str(obs)
    return text[:max_chars * 2]


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
    invalid_streak = 0  # p6.7：连续无效工具名计数（幻觉兜底）

    def _emit(ev: Event) -> None:
        if emit is not None:
            emit(ev)

    for i in range(1, max_iterations + 1):
        step = brain.next_step(task, history)
        if emitter is not None and step.thought:
            _emit(emitter.thinking_delta(step.thought))

        if step.final is not None:
            # p6.3：brain 已逐字推过（streamed）则只记录，不再整段重发
            # p6.7：JSON 包装的终答（chunked）按 5 字/块切片推——视觉等同打字机
            if emitter is not None:
                if getattr(step, "chunked", False):
                    text = step.final
                    for k in range(0, len(text), 5):
                        _emit(emitter.content_delta(text[k:k + 5]))
                        time.sleep(0.012)
                elif not step.streamed:
                    _emit(emitter.content_delta(step.final))
            history.append(step)
            return AgentResult(final=step.final, steps=history, iterations=i)

        # Action → 工具调用 → Observation
        name = step.action or ""
        if getattr(step, "invalid_action", False):
            # p6.7：LLM 幻觉出无效工具名（如 "none"）——不真调工具，给纠错观察；
            # 连续 2 次无效 → 强制如实收尾（过程透明，不空转）。
            invalid_streak += 1
            hint = f"无效工具名 {name!r}；可用工具：{list(tools.names())}。任务已完成时请直接写自然语言终答。"
            if emitter is not None:
                _emit(emitter.observation(name, hint))
            step.observation = hint
            history.append(step)
            if invalid_streak >= 2:
                done_steps = [s for s in history if s.observation]
                cap = (
                    f"模型连续给出无效工具名，已强制停止。已完成：{len(done_steps)} 步"
                    f"（如 " + "、".join(s.action or "?" for s in done_steps[-3:]) + "）。"
                    "请检查可用工具列表后重试，或换一种问法。"
                )
                if emitter is not None:
                    _emit(emitter.content_delta(cap))
                return AgentResult(final=cap, steps=history, iterations=i, hit_cap=True)
            continue
        if emitter is not None:
            _emit(emitter.tool_call_start(name, name, step.action_input))
        res: ToolResult = tools.call(name, **step.action_input)
        obs = res.output if res.ok else (res.error or "工具调用失败")
        if emitter is not None:
            # 前端步骤面板展示口径（p6.9：500 → 2000，用户能看到更多过程细节）
            _emit(emitter.observation(name, str(obs)[:2000]))
            _emit(
                emitter.tool_call_end(
                    name, name, success=res.ok, error=None if res.ok else (res.error or "")
                )
            )
        # p6.7：进 history 的是可读摘要（不是 str(dict) 全文），LLM 上下文卫生
        step.observation = _summarize_observation(obs) if res.ok else str(obs)[:500]
        history.append(step)

    # 超限：强制阶段结论（不硬编答案，只如实说明已达上限）
    cap = f"已达 max_iterations={max_iterations}，强制给出阶段结论"
    if emitter is not None:
        _emit(emitter.content_delta(cap))
    return AgentResult(final=cap, steps=history, iterations=max_iterations, hit_cap=True)
