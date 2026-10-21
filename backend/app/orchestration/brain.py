"""Brain 实现（p5.1a）——LLM 决策脑 + 配置驱动回落。

LlmBrain 实现 p4.1 的 `Brain` 协议（`next_step(task, history) -> Step`）：
  · 把 任务 + ReAct 历史 + 工具清单 编排成提示词，要求 LLM 每步只输出一个 JSON：
      调工具  {"thought": "...", "action": "工具名", "action_input": {...}}
      给终答  {"thought": "...", "final": "面向用户的最终回答"}
  · 输出解析失败 / LLM 不可用 → 如实给阶段结论（**不胡编**，§四.5）。
  · 每步 usage 累计到 `brain.usage` —— graph 据此做 token 两段式结算（§十四）。

make_brain()：配置驱动。模型+密钥就绪 → LlmBrain；否则回落 StubBrain
（确定性基线，零成本可测——测试环境永远走它，行为与 p4.1 一致）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from ..core.config import settings
from ..core.llm import (
    LlmError,
    LlmResult,
    chat as default_chat,
    chat_stream as default_chat_stream,
    resolve_model,
)
from .react import Brain, Step, StubBrain
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


def looks_like_json(text: str) -> bool:
    return (text or "").lstrip().startswith("{")

#: ReAct 输出协议（§四.4）——**统一在这里保证**，不写进各 Agent 的角色提示词（避免漂移）。
#: p6.3 流式：完成态改为"直接写自然语言终答"（不包 JSON），使 LLM 输出可逐字流式转发。
#: p6.7：显式禁止 action=none/无效名（真跑见证 LLM 幻觉 "none" 导致空转终止）。
_PROTOCOL_TMPL = """你的每一步【只能二选一输出】：
  A. 需要调用工具：输出一个 JSON 对象（除此之外不要有任何文字）：
     {{"thought": "你的思考", "action": "工具名", "action_input": {{...}}}}
     action 只能是上面工具清单里的名字，禁止使用 "none" 或任何不存在的工具名。
  B. 任务已完成：直接写面向用户的最终回答（自然语言，中文，可直接使用；不要包 JSON、不要复述结构）
     总结/分析/问答/整理类任务不需要调用任何工具——直接把答案写给用户。

可用工具（名字必须完全一致）：
{tools}

纪律：
  · 工具不存在/调用失败/观察结果为空时，在最终回答里【如实说明】，绝不编造数据或结论。
  · 尽快给出最终回答，通常不超过 {max_steps} 步。
  · 绝不允许出现 "action": "none" / "action": null——想结束就按 B 直接写答案。
"""


def extract_json(text: str) -> dict[str, Any] | None:
    """从 LLM 回复里提取第一个 JSON 对象；失败返回 None（不猜、不编）。"""
    s = (text or "").strip()
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(s[start : end + 1])
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


class ChatFn(Protocol):
    def __call__(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        *,
        timeout: float | None = None,
        temperature: float = ...,
        transport: Any = ...,
    ) -> LlmResult: ...


class ChatStreamFn(Protocol):
    def __call__(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        *,
        on_chunk: Any = ...,
        on_thought: Any = ...,
        timeout: float | None = None,
        temperature: float = ...,
        transport: Any = ...,
    ) -> LlmResult: ...


class LlmBrain:
    """LLM 决策脑。`usage` 供 graph 做真实 token 结算（§十四）。

    p6.3 流式模式（stream=True）：
      · LLM 输出以 `{` 开头 → ReAct JSON 协议，等完整再解析（工具步骤不需要逐字）；
      · 其他输出 → 视为面向用户的最终回答，**边收边推 on_content**（真打字机）；
      · 思考内容（reasoning_content）实时推 on_thought。
    """

    def __init__(
        self,
        *,
        model_id: str,
        tools: ToolRegistry,
        chat_fn: ChatFn | None = None,
        chat_stream_fn: ChatStreamFn | None = None,
        timeout: float | None = None,
        max_steps_hint: int = 8,
        system_prompt: str | None = None,
        stream: bool = False,
        on_content: Callable[[str], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
    ) -> None:
        self.model_id = model_id
        self._tools = tools
        self._chat: ChatFn = chat_fn or default_chat
        self._chat_stream: ChatStreamFn = chat_stream_fn or default_chat_stream
        self._timeout = timeout
        self._max_steps_hint = max_steps_hint
        # p5.1b：AgentSpec 的角色指令（config/agents.yaml）；None 用通用角色
        self._custom_system = (system_prompt or "").strip() or None
        self._stream = stream
        self._on_content = on_content
        self._on_thought = on_thought
        self.usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }

    def _accumulate(self, res: LlmResult) -> None:
        self.usage["prompt_tokens"] += res.prompt_tokens
        self.usage["completion_tokens"] += res.completion_tokens
        self.usage["total_tokens"] += res.total_tokens
        self.usage["calls"] += 1

    def _system_prompt(self) -> str:
        tools = "\n".join(
            f"- {t['name']}: {t['description'] or '（无描述）'}" for t in self._tools.describe()
        )
        if not tools:
            tools = "（当前没有任何工具——需要数据时请在 final 中如实说明该能力暂缺）"
        role = self._custom_system or "你是企业办公助手系统中一个业务 Agent（ReAct 模式）。"
        return f"{role}\n\n{_PROTOCOL_TMPL.format(tools=tools, max_steps=self._max_steps_hint)}"

    @staticmethod
    def _render_history(history: list[Step]) -> str:
        if not history:
            return "（尚无步骤）"
        lines = []
        for i, st in enumerate(history, 1):
            line = f"{i}. 思考：{st.thought or '（无）'}"
            if st.action:
                line += f" | 动作：{st.action}({json.dumps(st.action_input, ensure_ascii=False)})"
            if st.observation is not None:
                # p6.9：400 → 24000——原 400 字截断让 LLM"通读"时只看到文档开头
                # （真跑见证：2 万字文档读到"一句话价值"即断，LLM 以为工具只返回片段）
                obs = st.observation[:24000]
                line += f" | 观察：{obs}{'…（已截断）' if len(st.observation) > 24000 else ''}"
            lines.append(line)
        return "\n".join(lines)

    def next_step(self, task: str, history: list[Step]) -> Step:  # noqa: D102 - 见类注释
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": f"任务：{task}\n\n已执行步骤：\n{self._render_history(history)}\n\n请给出下一步 JSON。",
            },
        ]
        if self._stream:
            return self._next_step_streaming(messages)
        try:
            res = self._chat(self.model_id, messages, timeout=self._timeout)
        except LlmError as e:
            logger.warning("LLM brain 调用失败，如实给阶段结论 | %s", e)
            return Step(thought="模型调用失败", final=f"模型暂不可用，无法继续完成该任务：{e}")
        self._accumulate(res)

        data = extract_json(res.content)
        if data is None:
            logger.warning("LLM brain 输出无法解析为 JSON，如实停止（不编造）")
            return Step(
                thought="模型输出无法解析",
                final="模型输出无法解析为决策 JSON，已停止本次任务（未编造结论）。请稍后重试。",
            )
        return self._step_from_json(data, thought_streamed=False)

    def _next_step_streaming(self, messages: list[dict[str, str]]) -> Step:
        """p6.3：流式下一步。自然语言输出边收边推 on_content；JSON 等完整解析。"""
        parts: list[str] = []
        thought_streamed = False

        def _on_thought(t: str) -> None:
            nonlocal thought_streamed
            thought_streamed = True
            if self._on_thought is not None:
                self._on_thought(t)

        def _on_chunk(c: str) -> None:
            parts.append(c)
            # 只有"已确定不是 JSON"才逐字推；JSON 协议等完整解析（步骤不逐字）
            if self._on_content is not None and not looks_like_json("".join(parts)):
                self._on_content(c)

        try:
            res = self._chat_stream(
                self.model_id,
                messages,
                on_chunk=_on_chunk,
                on_thought=_on_thought,
                timeout=self._timeout,
            )
        except LlmError as e:
            logger.warning("LLM brain 流式调用失败，如实给阶段结论 | %s", e)
            return Step(thought="模型调用失败", final=f"模型暂不可用，无法继续完成该任务：{e}")
        self._accumulate(res)

        text = res.content
        if not looks_like_json(text):
            # 自然语言终答：已逐字推过，标记 streamed 防 run_react 重复整段发
            return Step(thought="", final=text, streamed=True)
        data = extract_json(text)
        if data is None:
            logger.warning("LLM brain 输出无法解析为 JSON，如实停止（不编造）")
            return Step(
                thought="模型输出无法解析",
                final="模型输出无法解析为决策 JSON，已停止本次任务（未编造结论）。请稍后重试。",
            )
        return self._step_from_json(data, thought_streamed=thought_streamed)

    @staticmethod
    def _step_from_json(data: dict[str, Any], *, thought_streamed: bool) -> Step:
        thought = "" if thought_streamed else str(data.get("thought", ""))
        if data.get("final") is not None:
            final = str(data["final"])
            # p6.7：LLM 偶尔仍用 JSON 包装终答——按 5 字/块切片推（视觉等同打字机，
            # 避免"思考半天答案整段蹦出来"；自然语言路径本就是真 chunk 流）
            return Step(thought=thought, final=final, streamed=True, chunked=True)
        action = data.get("action")
        action_str = str(action).strip() if action is not None else ""
        if not action_str or action_str.lower() in ("none", "null"):
            # 无效 action：标记 invalid_action 让 run_react 纠错（不空转停止）
            return Step(thought=thought or "（模型给出了无效动作）", invalid_action=True)
        action_input = data.get("action_input")
        if not isinstance(action_input, dict):
            action_input = {"input": action_input}
        return Step(thought=thought, action=action_str, action_input=action_input)


def make_brain(
    tools: ToolRegistry,
    *,
    fallback_answer: str = "处理完成",
    model_id: str | None = None,
    chat_fn: ChatFn | None = None,
    system_prompt: str | None = None,
    stream: bool = False,
    on_content: Callable[[str], None] | None = None,
    on_thought: Callable[[str], None] | None = None,
) -> Brain:
    """配置驱动的 Brain 工厂：模型+密钥就绪 → LlmBrain；否则回落 StubBrain（可测基线）。"""
    mid = model_id or settings.llm_brain_model
    try:
        resolve_model(mid)
    except LlmError as e:
        logger.info("LLM brain 未就绪（%s），回落 StubBrain（确定性基线）", e)
        return StubBrain(fallback_answer)
    return LlmBrain(
        model_id=mid,
        tools=tools,
        chat_fn=chat_fn,
        timeout=settings.llm_timeout,
        system_prompt=system_prompt,
        stream=stream,
        on_content=on_content,
        on_thought=on_thought,
    )
