"""模型注册表（配置驱动，非硬编码）—— 设计文档 §十七（用户点6 明确要求）。

要点：
  · 对话用的大模型（云端，用户持有 SiliconFlow / DeepSeek key）列进对话下拉；
  · embedding / reranker / decision 等【中间小模型】也列在配置里，但 in_dialogue=false，
    只在后端逻辑里取用，不出现在对话模型列表；
  · 所有模型走 YAML 配置（backend/config/models.yaml），绝不硬编码。
  · yaml 懒导入：app 导入 / 单测无需依赖 pyyaml，只有真正读注册表才 import。
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import settings


class ModelEntry(BaseModel):
    id: str
    name: str
    provider: str
    in_dialogue: bool = False
    role: str | None = None  # 逻辑模型专用：embedding / reranker / decision
    multimodal_input: bool = False
    context_window: int = 0
    max_output: int = 0
    supports_reasoning: bool = False
    # 该模型真正生效的 reasoning_effort，从低到高。空列表表示不要下发该参数。
    # 界面固定三档 low/high/max，少于三档时由 map_reasoning_effort 把较低档合并。
    reasoning_efforts: list[str] = Field(default_factory=list)
    pool_ids: list[str] = Field(default_factory=list)
    cost_per_1k: float = 0.0
    api_model: str = ""  # 实际调用名（provider 的模型 id）
    base_url: str | None = None
    api_key_env: str | None = None
    description: str = ""  # p6.8：模型描述（前端下拉展示）
    # 下拉里上下文和思考/视觉之外还要露出的标签，例如参数规模、工具、续写。
    highlights: list[str] = Field(default_factory=list)


class ProviderEntry(BaseModel):
    base_url: str = ""
    api_key_env: str | None = None


def _resolve_config_path() -> Path:
    if settings.models_config:
        p = Path(settings.models_config)
        if p.exists():
            return p
    # 候选位置：容器 /app/config、backend/config（仓库内）、显式路径
    candidates = [
        Path("/app/config/models.yaml"),
        Path(__file__).resolve().parents[2] / "config" / "models.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "models.yaml 未找到；请设置 MODELS_CONFIG 或放到 backend/config/models.yaml"
    )


@functools.lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    import yaml  # 懒导入，隔离重依赖

    raw = _resolve_config_path().read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    models = [ModelEntry(**m) for m in data.get("models", [])]
    providers = {k: ProviderEntry(**v) for k, v in data.get("llm_providers", {}).items()}
    return {"models": models, "providers": providers}


def get_dialogue_models(pool_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """对话下拉可见模型（§十七.1 字段）。pool_ids 为空表示不过滤。"""
    reg = load_registry()
    out: list[dict[str, Any]] = []
    for m in reg["models"]:
        if not m.in_dialogue:
            continue
        if pool_ids and not (set(m.pool_ids) & set(pool_ids)):
            continue
        out.append(
            {
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "multimodal_input": m.multimodal_input,
                "context_window": m.context_window,
                "max_output": m.max_output,
                "supports_reasoning": m.supports_reasoning,
                "pool_ids": m.pool_ids,
                "cost_per_1k": m.cost_per_1k,
                "description": m.description,
                "highlights": list(m.highlights),
            }
        )
    return out


def get_logic_model(role: str) -> ModelEntry | None:
    """取后端逻辑专用小模型（embedding / reranker / decision）。"""
    reg = load_registry()
    for m in reg["models"]:
        if m.role == role:
            return m
    return None


def get_provider(name: str) -> ProviderEntry | None:
    return load_registry()["providers"].get(name)


def supports_reasoning(model_id: str | None) -> bool:
    """该对话模型是否会思考。未注册则否。"""
    if not model_id:
        return False
    reg = load_registry()
    entry = next((m for m in reg["models"] if m.id == model_id), None)
    return bool(entry and entry.supports_reasoning)


_EFFORT_ALIAS = {"minimal": "low", "medium": "high", "xhigh": "max"}


def map_reasoning_effort(model_id: str | None, requested: str | None) -> str | None:
    """把界面三档（low/high/max）收成该模型真正接受的档。

    模型没有 reasoning_efforts 时返回 None（不下发，避免 400）。
    两档模型：low 与 high 都落到较低那一档，只有 max 落到最高档。
    三档模型：一一对应。
    """
    if not model_id or not requested:
        return None
    requested = _EFFORT_ALIAS.get(requested, requested)
    if requested == "none":
        return None
    reg = load_registry()
    entry = next((m for m in reg["models"] if m.id == model_id), None)
    levels = [x for x in (entry.reasoning_efforts if entry else []) if x]
    if not levels:
        return None
    if requested == "max":
        return levels[-1]
    if len(levels) >= 3 and requested in levels:
        return requested
    return levels[0]
