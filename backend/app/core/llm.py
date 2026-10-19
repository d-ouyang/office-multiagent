"""LLM 客户端（p5.1a）——OpenAI 兼容 /chat/completions，配置驱动。

- 模型与 provider 全部来自 `config/models.yaml`（p1.2 注册表）：base_url、api_key_env、
  api_model 都在表里；密钥只存环境变量/Settings，不进代码、不进仓库。
- 未配 key / 模型不在表 → `LlmNotConfigured`（fail-closed：调用方如实告知"能力不可用"，
  绝不假装成功或编造）。
- 返回 `LlmResult(content, usage)` —— usage 是 §十四 token 两段式结算的真实数据源。
- httpx transport 可注入（测试用 MockTransport，不真花钱、不出网）。
"""
from __future__ import annotations

import os
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
    transport: httpx.BaseTransport | None = None,
) -> LlmResult:
    """调一次 /chat/completions。任何失败抛 LlmError（含 LlmNotConfigured）。"""
    base_url, api_key, api_model = resolve_model(model_id)
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": api_model,
        "messages": messages,
        "temperature": temperature,
    }
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
