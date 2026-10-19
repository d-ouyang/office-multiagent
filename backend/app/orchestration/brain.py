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
from ..core.llm import LlmError, LlmResult, chat as default_chat, resolve_model
from .react import Brain, Step, StubBrain
from .tools import ToolRegistry

logger = logging.getLogger(__name__)

#: LLM 每步输出的提示词（§四.4 ReAct：Thought → Action → Observation）
_SYSTEM_TMPL = """你是办公助手系统中一个业务 Agent 的决策脑（ReAct 模式）。
你的每一步【只能输出一个 JSON 对象，不要输出任何其他文字】：
  需要调用工具：{{"thought": "你的思考", "action": "工具名", "action_input": {{...}}}}
  任务已完成：{{"thought": "你的思考", "final": "面向用户的最终回答（中文，直接可用）"}}

可用工具（名字必须完全一致）：
{tools}

纪律：
  · 工具不存在/调用失败/观察结果为空时，在 final 里【如实说明】，绝不编造数据或结论。
  · 尽快给出 final，通常不超过 {max_steps} 步。
  · final 必须直接面向用户，不要复述 JSON 结构。
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


class LlmBrain:
    """LLM 决策脑。`usage` 供 graph 做真实 token 结算（§十四）。"""

    def __init__(
        self,
        *,
        model_id: str,
        tools: ToolRegistry,
        chat_fn: ChatFn | None = None,
        timeout: float | None = None,
        max_steps_hint: int = 8,
    ) -> None:
        self.model_id = model_id
        self._tools = tools
        self._chat: ChatFn = chat_fn or default_chat
        self._timeout = timeout
        self._max_steps_hint = max_steps_hint
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
        return _SYSTEM_TMPL.format(tools=tools, max_steps=self._max_steps_hint)

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
                obs = st.observation[:400]
                line += f" | 观察：{obs}{'…' if len(st.observation) > 400 else ''}"
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
        thought = str(data.get("thought", ""))
        if data.get("final") is not None:
            return Step(thought=thought, final=str(data["final"]))
        action = data.get("action")
        if not action:
            return Step(thought=thought, final="模型未给出有效动作或结论，已停止本次任务。")
        action_input = data.get("action_input")
        if not isinstance(action_input, dict):
            action_input = {"input": action_input}
        return Step(thought=thought, action=str(action), action_input=action_input)


def make_brain(
    tools: ToolRegistry,
    *,
    fallback_answer: str = "处理完成",
    model_id: str | None = None,
    chat_fn: ChatFn | None = None,
) -> Brain:
    """配置驱动的 Brain 工厂：模型+密钥就绪 → LlmBrain；否则回落 StubBrain（可测基线）。"""
    mid = model_id or settings.llm_brain_model
    try:
        resolve_model(mid)
    except LlmError as e:
        logger.info("LLM brain 未就绪（%s），回落 StubBrain（确定性基线）", e)
        return StubBrain(fallback_answer)
    return LlmBrain(model_id=mid, tools=tools, chat_fn=chat_fn, timeout=settings.llm_timeout)
