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
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings
from .model_registry import load_registry


class LlmError(RuntimeError):
    """LLM 调用失败（网络/非 200/响应畸形）。"""


class LlmNotConfigured(LlmError):
    """模型未配置（不在注册表 / 缺密钥）。调用方应如实告知能力不可用。"""


@dataclass
class LlmResult:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""


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
    transport: httpx.BaseTransport | None = None,
) -> LlmResult:
    """调一次 /chat/completions（非流式，网络类失败自动重试 2 次）。

    任何失败抛 LlmError（含 LlmNotConfigured）。
    """
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            return _chat_once(
                model_id,
                messages,
                timeout=timeout,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                transport=transport,
            )
        except LlmError as e:
            last_err = e
            # 只重试网络类瞬时错误；4xx（鉴权/参数）重试无意义
            if not _is_transient(e) or attempt == 2:
                raise
            time.sleep(0.8 * (attempt + 1))
    raise last_err  # pragma: no cover - 循环必 return/raise


def _is_transient(e: LlmError) -> bool:
    """网络类瞬时错误（DNS/连接/超时/5xx）才值得重试。"""
    msg = str(e)
    return any(k in msg for k in ("ConnectError", "Timeout", "timed out", "Name or service", "Connection", " 502", " 503", " 504"))


def _chat_once(
    model_id: str,
    messages: list[dict[str, str]],
    *,
    timeout: float | None = None,
    temperature: float = 0.2,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
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
        content = data["choices"][0]["message"]["content"] or ""
    except Exception as e:  # noqa: BLE001 - 响应畸形统一转 LlmError
        raise LlmError(f"LLM 响应畸形：{e}") from e
    usage = data.get("usage") or {}
    return LlmResult(
        content=str(content),
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
        model=api_model,
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
    transport: httpx.BaseTransport | None = None,
) -> LlmResult:
    """流式 /chat/completions（p6.3 真流式管道）。

    - 每个正文 chunk 立即回调 `on_chunk`（前端打字机的数据源）；
    - DeepSeek R1 等模型的思考内容（reasoning_content）回调 `on_thought`；
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
    headers = {"Authorization": f"Bearer {api_key}"}
    parts: list[str] = []
    usage: dict[str, Any] = {}
    last_err: Exception | None = None
    emitted_any = False  # 已向用户吐过任何内容（正文/思考）：重试会重复输出，只能如实终止
    for attempt in range(3):
        parts.clear()
        usage = {}
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
            return LlmResult(
                content="".join(parts),
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                total_tokens=int(usage.get("total_tokens", 0)),
                model=api_model,
            )
        except (httpx.HTTPError, LlmError) as e:
            last_err = e if isinstance(e, LlmError) else LlmError(f"LLM 请求失败：{type(e).__name__}: {e}")
            if emitted_any:
                raise last_err from e  # 已出字：重试会重复输出，如实终止
            if not _is_transient(last_err) or attempt == 2:
                raise last_err from e
            time.sleep(0.8 * (attempt + 1))
    raise last_err  # pragma: no cover
