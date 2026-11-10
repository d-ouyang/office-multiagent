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
from ..core.token_budget import TaskTokenBudget
from .react import Brain, Step, StubBrain
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


def looks_like_json(text: str) -> bool:
    return (text or "").lstrip().startswith("{")


def resolve_react_protocol(mode: str | None, model_id: str, tools: ToolRegistry) -> str:
    """v2.0.0-p1.5：解析 ReAct 协议（json | tool_calls）。

    - json：现状文本协议（fail-closed 缺省）。
    - tool_calls：强制走原生协议；模型不支持 → 告警回落 json（禁止硬开）。
    - auto：模型 supports_tools 且本轮工具全有 Schema 且工具非空 → tool_calls，否则 json。
    """
    mode = (mode or settings.react_protocol or "json").strip().lower()
    if mode not in ("json", "tool_calls", "auto"):
        logger.warning("react_protocol 配置非法：%r，回落 json", mode)
        return "json"
    if mode == "json":
        return "json"

    entry = None
    try:
        from ..core.model_registry import load_registry

        entry = next((m for m in load_registry()["models"] if m.id == model_id), None)
    except Exception:  # noqa: BLE001 - 注册表读不到按不支持处理
        entry = None
    supported = bool(entry and entry.supports_tools)
    schema_ready = bool(tools.names()) and not tools.schema_incomplete()
    if mode == "tool_calls":
        if not supported:
            logger.warning("模型 %s 未点测支持 tools（supports_tools=%s），tool_calls 回落 json", model_id, getattr(entry, "supports_tools", None))
            return "json"
        if not schema_ready:
            # 显式模式同样不开：无 Schema 工具会被 describe_openai 排除，硬开会静默退化
            logger.warning("工具 Schema 不完整（%s），tool_calls 回落 json", tools.schema_incomplete())
            return "json"
        return "tool_calls"
    # auto
    if supported and schema_ready:
        return "tool_calls"
    return "json"

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
  · 观察里已经有报表、数字或正文时，下一步按 B 写分析和建议，不要用相同参数再调同一个工具。
  · 数据确实缺失时，说明缺什么并停止。不要自己发明新的取数流程，也不要反复重试同一个工具。
  · 尽快给出最终回答，通常不超过 {max_steps} 步。
  · 绝不允许出现 "action": "none" / "action": null——想结束就按 B 直接写答案。
"""

#: v2.0.0-p1.3：tool_calls 模式的 system 提示词——**不包含** JSON 输出格式要求
#:（Prompt 债务红线：双协议并存时强迫 JSON 的段落必须收窄，否则模型双重格式）。
_TOOLCALLS_TMPL = """你可以通过 function calling 调用上面传入的工具；需要数据时调用工具，任务完成或无法完成时直接写面向用户的最终回答（自然语言，中文）。

纪律：
  · 工具不存在/调用失败/观察结果为空时，在最终回答里【如实说明】，绝不编造数据或结论。
  · 观察里已经有报表、数字或正文时，下一步直接写分析和建议，不要用相同参数再调同一个工具。
  · 数据确实缺失时，说明缺什么并停止。不要自己发明新的取数流程，也不要反复重试同一个工具。
  · 尽快给出最终回答，通常不超过 {max_steps} 步。
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
        reasoning_effort: str | None = None,
        token_budget: TaskTokenBudget | None = None,
        protocol: str | None = None,
    ) -> None:
        self.model_id = model_id
        self._tools = tools
        self._chat: ChatFn = chat_fn or default_chat
        self._chat_stream: ChatStreamFn = chat_stream_fn or default_chat_stream
        self._timeout = timeout
        self._max_steps_hint = max_steps_hint
        self._custom_system = (system_prompt or "").strip() or None
        self._stream = stream
        self._on_content = on_content
        self._on_thought = on_thought
        self._effort = reasoning_effort or None
        self._token_budget = token_budget
        # v2.0.0-p1.3：协议解析一次定终身（构造时按 model+工具集判定，运行期不变）。
        self.protocol = resolve_react_protocol(protocol, model_id, tools)
        self.usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_hit_tokens": 0,  # 2.1.0：上下文缓存命中（deepseek），供前端展示命中率
            "calls": 0,
        }

    def _accumulate(self, res: LlmResult) -> None:
        self.usage["prompt_tokens"] += res.prompt_tokens
        self.usage["completion_tokens"] += res.completion_tokens
        self.usage["total_tokens"] += res.total_tokens
        self.usage["cache_hit_tokens"] += int(getattr(res, "cache_hit_tokens", 0) or 0)
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
        if self.protocol == "tool_calls":
            return self._next_step_tool_calls(task, history)
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": f"任务：{task}\n\n已执行步骤：\n{self._render_history(history)}\n\n请给出下一步 JSON。",
            },
        ]
        if self._stream:
            return self._next_step_streaming(messages)
        reservation = (
            self._token_budget.reserve_call(messages)
            if self._token_budget is not None
            else None
        )
        try:
            kwargs: dict[str, Any] = {
                "timeout": self._timeout,
                "reasoning_effort": self._effort,
            }
            if reservation is not None:
                kwargs["max_tokens"] = reservation.max_output_tokens
            res = self._chat(self.model_id, messages, **kwargs)
        except Exception as e:
            if reservation is not None:
                reservation.cancel()
            if not isinstance(e, LlmError):
                raise
            logger.warning("LLM brain 调用失败，如实给阶段结论 | %s", e)
            return Step(thought="模型调用失败", final=f"模型暂不可用，无法继续完成该任务：{e}")
        if reservation is not None:
            reservation.complete(res.total_tokens)
        self._accumulate(res)

        data = extract_json(res.content)
        if data is None:
            if looks_like_json(res.content):
                # 以 { 开头但不是合法 JSON → 真解析失败，如实停止（不编造）
                logger.warning("LLM brain 输出无法解析为 JSON，如实停止（不编造）")
                return Step(
                    thought="模型输出无法解析",
                    final="模型输出无法解析为决策 JSON，已停止本次任务（未编造结论）。请稍后重试。",
                )
            # 非 JSON 输出 = 协议 B 的自然语言终答（p6.3 混合策略；此前非流式路径漏了
            # 这条，与流式路径 looks_like_json 判定不一致，p4.3b 真跑冒烟抓到）
            return Step(thought="", final=res.content, streamed=False)
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

        reservation = (
            self._token_budget.reserve_call(messages)
            if self._token_budget is not None
            else None
        )
        try:
            kwargs: dict[str, Any] = {
                "on_chunk": _on_chunk,
                "on_thought": _on_thought,
                "timeout": self._timeout,
                "reasoning_effort": self._effort,
            }
            if reservation is not None:
                kwargs["max_tokens"] = reservation.max_output_tokens
            res = self._chat_stream(self.model_id, messages, **kwargs)
        except Exception as e:
            if reservation is not None:
                reservation.cancel()
            if not isinstance(e, LlmError):
                raise
            logger.warning("LLM brain 流式调用失败，如实给阶段结论 | %s", e)
            return Step(thought="模型调用失败", final=f"模型暂不可用，无法继续完成该任务：{e}")
        if reservation is not None:
            reservation.complete(res.total_tokens)
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

    # ------------------------------------------------------------------ #
    # v2.0.0-p1.3：原生 tool_calls 协议路径
    # ------------------------------------------------------------------ #
    def _toolcalls_system_prompt(self) -> str:
        role = self._custom_system or "你是企业办公助手系统中一个业务 Agent。"
        return f"{role}\n\n{_TOOLCALLS_TMPL.format(max_steps=self._max_steps_hint)}"

    @staticmethod
    def _messages_for_tool_calls(task: str, history: list[Step]) -> list[dict[str, Any]]:
        """历史消息形态：assistant(tool_calls) → tool(tool_call_id)。

        红线（历史双写禁忌）：tool_calls 路径绝不把观察拼进 user 文本——观察只走
        role=tool 消息；同一轮也不存在两种历史形态。
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": ""},
            {"role": "user", "content": f"任务：{task}"},
        ]
        for i, st in enumerate(history, 1):
            if st.action is None:
                # 2.1.0 P1-1n hotfix：无工具调用的观察步（HITL 续跑 seed"用户已补充输入：…"）
                # 以 user 消息进入——生产实测该 Step 被跳过导致模型永远收不到用户回答，
                # 在 ask_user 后直接给终答。seed 是用户说的话，走 user 消息语义正确；
                # 工具观察仍只走 role=tool（红线不变）。
                if st.observation:
                    messages.append({"role": "user", "content": st.observation})
                continue
            if st.observation is None:
                continue
            call_id = st.call_id or f"call_{i}"
            messages.append({
                "role": "assistant",
                "content": st.thought or "",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": st.action,
                        "arguments": json.dumps(st.action_input, ensure_ascii=False, default=str),
                    },
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": (st.observation or "")[:24000],
            })
        return messages

    def _step_from_tool_calls(self, res: LlmResult, *, streamed: bool) -> Step:
        calls = [
            {
                "id": c.id,
                "name": c.name,
                "arguments": c.arguments,
                "parse_error": c.parse_error,
            }
            for c in res.tool_calls
        ]
        return Step(thought=res.content or "", calls=calls, streamed=streamed)

    def _next_step_tool_calls(self, task: str, history: list[Step]) -> Step:
        messages = self._messages_for_tool_calls(task, history)
        messages[0]["content"] = self._toolcalls_system_prompt()
        tools_api = self._tools.describe_openai()
        reservation = (
            self._token_budget.reserve_call(messages)
            if self._token_budget is not None
            else None
        )
        try:
            kwargs: dict[str, Any] = {
                "timeout": self._timeout,
                "reasoning_effort": self._effort,
                "tools": tools_api,
            }
            if reservation is not None:
                kwargs["max_tokens"] = reservation.max_output_tokens
            if self._stream:
                thought_parts: list[str] = []

                def _on_chunk(piece: str) -> None:
                    thought_parts.append(piece)
                    # tool_calls 路径：正文先按"可能是终答"逐字推（真打字机）。
                    # 若流末发现模型其实带了 tool_calls，已推片段归为思考（厂商惯例
                    # 工具轮 content 为空；见迭代文档已知限制）。
                    if self._on_content is not None:
                        self._on_content(piece)

                kwargs.update({
                    "on_chunk": _on_chunk,
                    "on_thought": self._on_thought,
                    "on_tool_call": lambda _call: None,
                })
                res = self._chat_stream(self.model_id, messages, **kwargs)
            else:
                res = self._chat(self.model_id, messages, **kwargs)
        except Exception as e:
            if reservation is not None:
                reservation.cancel()
            if not isinstance(e, LlmError):
                raise
            logger.warning("LLM brain（%s 协议）调用失败，如实给阶段结论 | %s", self.protocol, e)
            return Step(thought="模型调用失败", final=f"模型暂不可用，无法继续完成该任务：{e}")
        if reservation is not None:
            reservation.complete(res.total_tokens)
        self._accumulate(res)

        if res.tool_calls:
            return self._step_from_tool_calls(res, streamed=self._stream)
        # 无 tool_calls = 自然语言终答（流式已逐字推过；非流式整段交 run_react 推）
        return Step(thought="", final=res.content, streamed=self._stream)

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
    reasoning_effort: str | None = None,
    token_budget: TaskTokenBudget | None = None,
    protocol: str | None = None,
) -> Brain:
    """配置驱动的 Brain 工厂：模型+密钥就绪 → LlmBrain；否则回落 StubBrain（可测基线）。

    v2.0.0-p1.5：protocol 缺省读 settings.react_protocol（json | tool_calls | auto）；
    auto 按 models.yaml supports_tools + 工具 Schema 完整性自动判定。
    """
    # 2.1.0：系统提示注入当前日期/星期（模型无时间感知；全局生效，含 single/multi 子任务）
    from datetime import datetime as _dt

    _now = _dt.now()
    _date_block = f"【当前时间】{_now.strftime('%Y-%m-%d %H:%M')}（{_now.strftime('%A')}）。涉及'今天/昨天/上周/本月'等相对时间时，以此为准换算具体日期。"
    if system_prompt:
        system_prompt = f"{system_prompt}\n\n{_date_block}"
    else:
        system_prompt = _date_block

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
        reasoning_effort=reasoning_effort,
        token_budget=token_budget,
        protocol=protocol,
    )
