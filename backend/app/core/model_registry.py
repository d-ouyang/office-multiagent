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
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import settings

_EDITABLE_FIELDS = (
    "name",
    "provider",
    "in_dialogue",
    "enabled",
    "role",
    "multimodal_input",
    "context_window",
    "max_output",
    "supports_reasoning",
    "supports_tools",
    "reasoning_efforts",
    "pool_ids",
    "cost_per_1k",
    "api_model",
    "description",
)


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
    # 三态：None=未点测（auto 必须回退 json）；只有逐模型真点测通过才置 True。
    supports_tools: bool | None = None
    # 该模型真正生效的 reasoning_effort，从低到高。空列表表示不要下发该参数。
    # 界面固定三档 low/high/max，少于三档时由 map_reasoning_effort 把较低档合并。
    reasoning_efforts: list[str] = Field(default_factory=list)
    pool_ids: list[str] = Field(default_factory=list)
    cost_per_1k: float = 0.0
    api_model: str = ""  # 实际调用名（provider 的模型 id）
    base_url: str | None = None
    api_key_env: str | None = None
    description: str = ""  # p6.8：模型描述（前端下拉展示）
    enabled: bool = True  # 管理端可关；关闭后不进对话下拉，逻辑模型也不再被取用


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


def _overrides_path() -> Path:
    return _resolve_config_path().with_name("models.overrides.yaml")


def _load_overrides() -> dict[str, dict[str, Any]]:
    import yaml

    path = _overrides_path()
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, Any]] = {}
    for item in data.get("models", []) if isinstance(data, dict) else []:
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = {k: v for k, v in item.items() if k != "id"}
    return out


_MODEL_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def _apply_overrides(models: list[ModelEntry]) -> list[ModelEntry]:
    overrides = _load_overrides()
    if not overrides:
        return models
    merged: list[ModelEntry] = []
    seen: set[str] = set()
    for model in models:
        seen.add(model.id)
        patch = overrides.get(model.id)
        if not patch:
            merged.append(model)
            continue
        payload = model.model_dump()
        for key in _EDITABLE_FIELDS:
            if key in patch:
                payload[key] = patch[key]
        merged.append(ModelEntry(**payload))
    # 管理端「新建模型」只写 overrides，不进手写 yaml，这里补进登记表。
    for mid, patch in overrides.items():
        if mid in seen or not isinstance(patch, dict):
            continue
        try:
            merged.append(ModelEntry(**{"id": mid, **patch}))
        except Exception:  # noqa: BLE001 - 坏掉的覆盖行跳过，不拖垮整张登记表
            continue
    return merged


@functools.lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    import yaml  # 懒导入，隔离重依赖

    raw = _resolve_config_path().read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    models = _apply_overrides([ModelEntry(**m) for m in data.get("models", [])])
    providers = {k: ProviderEntry(**v) for k, v in data.get("llm_providers", {}).items()}
    return {"models": models, "providers": providers}


def reload_registry() -> dict[str, Any]:
    load_registry.cache_clear()
    return load_registry()


def list_catalog() -> list[dict[str, Any]]:
    """管理端模型清单（含逻辑模型与关闭项）。"""
    return [m.model_dump() for m in load_registry()["models"]]


def _write_overrides(overrides: dict[str, dict[str, Any]]) -> None:
    import yaml

    path = _overrides_path()
    payload = {"models": [{"id": mid, **fields} for mid, fields in overrides.items()]}
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    reload_registry()


def update_model(model_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """把管理端改动写进 models.overrides.yaml，不改手写的 models.yaml。"""
    entry = next((m for m in load_registry()["models"] if m.id == model_id), None)
    if entry is None:
        raise KeyError(model_id)
    clean = {k: patch[k] for k in _EDITABLE_FIELDS if k in patch}
    if not clean:
        return entry.model_dump()
    overrides = _load_overrides()
    current = overrides.get(model_id, {})
    current.update(clean)
    overrides[model_id] = current
    _write_overrides(overrides)
    updated = next(m for m in load_registry()["models"] if m.id == model_id)
    return updated.model_dump()


def create_model(payload: dict[str, Any]) -> dict[str, Any]:
    """在 overrides 里新增一条对话模型登记（不改手写 yaml）。"""
    mid = str(payload.get("id") or "").strip()
    if not _MODEL_ID_RE.match(mid):
        raise ValueError("登记 id 仅允许字母、数字、点、下划线和连字符")
    name = str(payload.get("name") or "").strip()
    provider = str(payload.get("provider") or "").strip()
    api_model = str(payload.get("api_model") or "").strip()
    if not name:
        raise ValueError("名称不能为空")
    if not provider:
        raise ValueError("渠道不能为空")
    if not api_model:
        raise ValueError("实际调用名不能为空")
    if any(m.id == mid for m in load_registry()["models"]):
        raise KeyError(mid)
    fields: dict[str, Any] = {
        "name": name,
        "provider": provider,
        "api_model": api_model,
        "description": str(payload.get("description") or ""),
        "in_dialogue": bool(payload.get("in_dialogue", True)),
        "enabled": bool(payload.get("enabled", True)),
        "context_window": int(payload.get("context_window") or 0),
        "max_output": int(payload.get("max_output") or 0),
        "cost_per_1k": float(payload.get("cost_per_1k") or 0),
        "supports_reasoning": bool(payload.get("supports_reasoning") or False),
        "multimodal_input": bool(payload.get("multimodal_input") or False),
        "pool_ids": list(payload.get("pool_ids") or ["default", "staff", "admin"]),
    }
    if payload.get("reasoning_efforts"):
        fields["reasoning_efforts"] = list(payload["reasoning_efforts"])
    overrides = _load_overrides()
    overrides[mid] = fields
    _write_overrides(overrides)
    created = next(m for m in load_registry()["models"] if m.id == mid)
    return created.model_dump()


def get_dialogue_models(pool_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """对话下拉可见模型（§十七.1 字段）。pool_ids 为空表示不过滤。"""
    reg = load_registry()
    out: list[dict[str, Any]] = []
    for m in reg["models"]:
        if not m.in_dialogue or not m.enabled:
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
            }
        )
    return out


def get_logic_model(role: str) -> ModelEntry | None:
    """取后端逻辑专用小模型（embedding / reranker / decision）。"""
    reg = load_registry()
    for m in reg["models"]:
        if m.role == role and m.enabled:
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
