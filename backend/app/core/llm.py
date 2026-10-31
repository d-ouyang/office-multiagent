"""LLM 客户端（p5.1a）——OpenAI 兼容 /chat/completions，配置驱动。

- 模型与 provider 全部来自 `config/models.yaml`（p1.2 注册表）：base_url、api_key_env、
  api_model 都在表里；密钥只存环境变量/Settings，不进代码、不进仓库。
- 未配 key / 模型不在表 → `LlmNotConfigured`（fail-closed：调用方如实告知"能力不可用"，
  绝不假装成功或编造）。
- 返回 `LlmResult(content, usage)` —— usage 是 §十四 token 两段式结算的真实数据源。
- httpx transport 可注入（测试用 MockTransport，不真花钱、不出网）。
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field
from typing import Any

import httpx

from .config import settings
from .model_registry import load_registry

logger = logging.getLogger(__name__)


class LlmError(RuntimeError):
    """LLM 调用失败（网络/非 200/响应畸形）。"""


class LlmNotConfigured(LlmError):
    """模型未配置（不在注册表 / 缺密钥）。调用方应如实告知能力不可用。"""


@dataclass
class ToolCall:
    """原生 tool_calls 的归一化结构（v2.0.0-p1.2）。

    arguments 解析失败不抛异常：记录 parse_error，由上层回填为工具错误（红线：
    不把坏参数抬成整图故障，也不静默丢弃）。
    """

    id: str
    name: str
    arguments: dict[str, Any]
    arguments_raw: str = ""
    parse_error: str | None = None


@dataclass
class LlmResult:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    tool_calls: list[ToolCall] = dataclass_field(default_factory=list)


def _parse_tool_calls(raw_calls: Any) -> list[ToolCall]:
    """把响应里的 message.tool_calls / 流式增量还原成 ToolCall（缺 id/name 视为协议畸形）。"""
    calls: list[ToolCall] = []
    for raw in raw_calls or []:
        if not isinstance(raw, dict):
            raise LlmError(f"LLM tool_calls 畸形：非对象元素 {raw!r}")
        fn = raw.get("function") or {}
        call_id = str(raw.get("id") or "")
        name = str(fn.get("name") or "")
        if not call_id or not name:
            raise LlmError("LLM tool_calls 畸形：缺 id 或 function.name")
        arguments_raw = fn.get("arguments")
        arguments_raw = "" if arguments_raw is None else str(arguments_raw)
        arguments: dict[str, Any] = {}
        parse_error: str | None = None
        if arguments_raw:
            try:
                parsed = json.loads(arguments_raw)
                if not isinstance(parsed, dict):
                    parse_error = "arguments 不是 JSON object"
                else:
                    arguments = parsed
            except ValueError as e:
                parse_error = f"arguments JSON 解析失败：{e}"
        calls.append(
            ToolCall(
                id=call_id,
                name=name,
                arguments=arguments,
                arguments_raw=arguments_raw,
                parse_error=parse_error,
            )
        )
    return calls


def _apply_tools_payload(
    payload: dict[str, Any],
    tools: list[dict[str, Any]] | None,
    tool_choice: str | dict[str, Any] | None,
) -> None:
    """tools 非空才下发；缺省 tool_choice=auto（OpenAI 兼容语义）。"""
    if not tools:
        return
    payload["tools"] = tools
    payload["tool_choice"] = tool_choice or "auto"


def _extract_message_tool_calls(message: Any) -> list[ToolCall]:
    return _parse_tool_calls(message.get("tool_calls")) if isinstance(message, dict) else []


def load_api_key(api_key_env: str) -> str:
    """按注册表里的 api_key_env 取密钥：先 Settings 字段（pydantic 吸进来的），再环境变量。"""
    if not api_key_env:
        return ""
    attr = api_key_env.lower()
    val = getattr(settings, attr, None)
    if val:
        return str(val)
    return os.environ.get(api_key_env, "")


def resolve_model(model_id: str) -> tuple[str, str, str]:
    """model_id → (base_url, api_key, api_model)。未就绪抛 LlmNotConfigured。"""
    registry = load_registry()
    entry = next((m for m in registry.get("models", []) if m.id == model_id), None)
    if entry is None:
        raise LlmNotConfigured(f"模型 {model_id} 不在注册表中（config/models.yaml）")
    provider = registry.get("providers", {}).get(entry.provider)
    base_url = str(provider.base_url) if provider else ""
    api_key = load_api_key(
        str(getattr(entry, "api_key_env", "") or getattr(provider, "api_key_env", "") or "")
    )
    api_model = str(entry.api_model or model_id)
    if not base_url or not api_key:
        raise LlmNotConfigured(
            f"模型 {model_id} 未就绪：base_url={'有' if base_url else '缺'}，key 缺（见注册表 api_key_env）"
        )
    return base_url, api_key, api_model


def chat(
    model_id: str,
    messages: list[dict[str, str]],
    *,
    timeout: float | None = None,
    temperature: float = 0.2,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> LlmResult:
    """调一次 /chat/completions（非流式，网络类失败自动重试 2 次）。

    任何失败抛 LlmError（含 LlmNotConfigured）。
    tools 非空时下发 tools/tool_choice，响应里的 tool_calls 归一化为 ToolCall。
    """
    last_err: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            return _chat_once(
                model_id,
                messages,
                timeout=timeout,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice=tool_choice,
                transport=transport,
            )
        except LlmError as e:
            last_err = e
            # 只重试网络类瞬时错误与限流/5xx；其余 4xx（鉴权/参数）重试无意义
            if not _is_transient(e) or attempt >= settings.llm_max_retries:
                raise
            delay = _retry_delay(e, attempt)
            # p5.1 可观测性：重试必须留痕，否则生产上"这次任务怎么慢了几秒"无从排查
            logger.info(
                "LLM 瞬时失败，%.1fs 后重试（第 %d/%d 次）model=%s 原因=%s",
                delay, attempt + 1, settings.llm_max_retries, model_id, e,
            )
            time.sleep(delay)
    raise last_err  # pragma: no cover - 循环必 return/raise


#: 可重试的 HTTP 状态码——限流与服务端瞬时错误；其余 4xx（鉴权/参数）重试无意义。
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _status_code_of(e: LlmError) -> int | None:
    """从 `_chat_once` 的 `LLM 返回 <code>: <body>` 错误里提取状态码（无则 None）。"""
    msg = str(e)
    if not msg.startswith("LLM 返回 "):
        return None
    token = msg[len("LLM 返回 "):].split(":", 1)[0].strip()
    return int(token) if token.isdigit() else None


def _is_transient(e: LlmError) -> bool:
    """限流（429）/ 服务端瞬时错误（5xx）/ 网络类错误才值得重试。

    p5.1：原先纯字符串匹配只覆盖 502/503/504，**429 与 500 完全不重试**——而 multi
    层内并行（dag_max_concurrency=3）多个子任务同时打同一模型时，限流 429 恰是最需要
    退避重试的场景。现在状态码优先结构化判定，网络类错误保留字符串兜底。
    """
    code = _status_code_of(e)
    if code is not None:
        return code in _TRANSIENT_STATUS
    msg = str(e)
    return any(k in msg for k in ("ConnectError", "Timeout", "timed out", "Name or service", "Connection", " 502", " 503", " 504"))


def _retry_delay(e: LlmError, attempt: int) -> float:
    """退避时长：429 用独立（更长）基数——限流要等服务端窗口，与网络抖动不同量级。"""
    base = settings.llm_retry_backoff_429 if _status_code_of(e) == 429 else settings.llm_retry_backoff
    return base * (attempt + 1)


def _chat_once(
    model_id: str,
    messages: list[dict[str, str]],
    *,
    timeout: float | None = None,
    temperature: float = 0.2,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> LlmResult:
    base_url, api_key, api_model = resolve_model(model_id)
    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": api_model,
        "messages": messages,
        "temperature": temperature,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if max_tokens is not None:
        payload["max_tokens"] = max(1, int(max_tokens))
    _apply_tools_payload(payload, tools, tool_choice)
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=timeout or settings.llm_timeout, transport=transport) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise LlmError(f"LLM 请求失败：{type(e).__name__}: {e}") from e
    if resp.status_code != 200:
        raise LlmError(f"LLM 返回 {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        tool_calls = _parse_tool_calls(message.get("tool_calls"))
    except LlmError:
        raise
    except Exception as e:  # noqa: BLE001 - 响应畸形统一转 LlmError
        raise LlmError(f"LLM 响应畸形：{e}") from e
    usage = data.get("usage") or {}
    return LlmResult(
        content=str(content),
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
        model=api_model,
        tool_calls=tool_calls,
    )


def chat_stream(
    model_id: str,
    messages: list[dict[str, str]],
    *,
    on_chunk: Callable[[str], None] | None = None,
    on_thought: Callable[[str], None] | None = None,
    timeout: float | None = None,
    temperature: float = 0.2,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    on_tool_call: Callable[[ToolCall], None] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> LlmResult:
    """流式 /chat/completions（p6.3 真流式管道；v2.0.0-p1.2 支持 tool_calls 增量）。

    - 每个正文 chunk 立即回调 `on_chunk`（前端打字机的数据源）；
    - DeepSeek R1 等模型的思考内容（reasoning_content）回调 `on_thought`；
    - tool_calls 按 index 增量累积，**流结束后**逐个回调 `on_tool_call` 并随结果返回——
      正文/思考流与工具增量分通道，绝不交错污染；
    - usage 从流式末块取（stream_options.include_usage），token 结算不受影响；
    - **首个 chunk 到达前**的网络类失败自动重试 2 次（已出字后失败不重试——重复输出
      比失败更糟）；任何最终失败抛 LlmError，调用方如实告知。
    """
    base_url, api_key, api_model = resolve_model(model_id)
    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": api_model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if max_tokens is not None:
        payload["max_tokens"] = max(1, int(max_tokens))
    _apply_tools_payload(payload, tools, tool_choice)
    headers = {"Authorization": f"Bearer {api_key}"}
    parts: list[str] = []
    usage: dict[str, Any] = {}
    raw_calls: dict[int, dict[str, Any]] = {}
    last_err: Exception | None = None
    emitted_any = False  # 已向用户吐过任何内容（正文/思考）：重试会重复输出，只能如实终止
    for attempt in range(settings.llm_max_retries + 1):
        parts.clear()
        usage = {}
        raw_calls.clear()
        try:
            with httpx.Client(timeout=timeout or settings.llm_timeout, transport=transport) as client:
                with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        raise LlmError(
                            f"LLM 返回 {resp.status_code}: {resp.read().decode('utf-8', 'replace')[:200]}"
                        )
                    for line in resp.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except ValueError:
                            continue
                        if obj.get("usage"):
                            usage = obj["usage"]
                        for choice in obj.get("choices") or []:
                            delta = (choice.get("delta") or {}) if isinstance(choice, dict) else {}
                            piece = delta.get("content") or ""
                            if piece:
                                emitted_any = True
                                parts.append(piece)
                                if on_chunk is not None:
                                    on_chunk(piece)
                            thought = delta.get("reasoning_content") or ""
                            if thought and on_thought is not None:
                                emitted_any = True
                                on_thought(thought)
                            for part in delta.get("tool_calls") or []:
                                index = int(part.get("index") or 0)
                                slot = raw_calls.setdefault(
                                    index, {"id": "", "function": {"name": "", "arguments": ""}}
                                )
                                if part.get("id"):
                                    slot["id"] += str(part["id"])
                                fn_part = part.get("function") or {}
                                if fn_part.get("name"):
                                    slot["function"]["name"] += str(fn_part["name"])
                                if fn_part.get("arguments") is not None:
                                    slot["function"]["arguments"] += str(fn_part["arguments"])
            tool_calls = _parse_tool_calls([raw_calls[k] for k in sorted(raw_calls)])
            for call in tool_calls:
                if on_tool_call is not None:
                    on_tool_call(call)
            return LlmResult(
                content="".join(parts),
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                total_tokens=int(usage.get("total_tokens", 0)),
                model=api_model,
                tool_calls=tool_calls,
            )
        except (httpx.HTTPError, LlmError) as e:
            last_err = e if isinstance(e, LlmError) else LlmError(f"LLM 请求失败：{type(e).__name__}: {e}")
            if emitted_any:
                raise last_err from e  # 已出字：重试会重复输出，如实终止
            if not _is_transient(last_err) or attempt >= settings.llm_max_retries:
                raise last_err from e
            delay = _retry_delay(last_err, attempt)
            logger.info(
                "LLM 流式首块前瞬时失败，%.1fs 后重试（第 %d/%d 次）model=%s 原因=%s",
                delay, attempt + 1, settings.llm_max_retries, model_id, last_err,
            )
            time.sleep(delay)
    raise last_err  # pragma: no cover
