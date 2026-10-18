"""任务规划器（p3.1）——设计文档 §四.2：意图识别 + 复杂度打分。

纪律（§十二 / JEV 决策层接口化）：意图分类 + 复杂度评分是「高频、低延迟、确定性」
判断，用【配置驱动的确定性规则】打底——可测、零 LLM 成本、无网络抖动；
LLM 增强（DAG 分解、歧义消解）留作后续 DecisionModel 插槽，改配置即可接。
DAG 分解（§四.2 第三步）在 p3.2 落地，本模块先覆盖意图 + 复杂度。
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import settings


@dataclass
class Plan:
    text: str
    intents: list[str] = field(default_factory=list)      # 涉及意图（命中强度降序，主意图在前）
    intent_hits: dict[str, int] = field(default_factory=dict)
    score: float = 0.0                                    # 复杂度分
    signals: dict[str, Any] = field(default_factory=dict)  # 打分明细（可解释、可对账）
    entities: dict[str, Any] = field(default_factory=dict)  # 抽取实体（输出格式等）


def _resolve_planner_path() -> Path:
    if settings.planner_config:
        p = Path(settings.planner_config)
        if p.exists():
            return p
    for c in (
        Path("/app/config/planner.yaml"),
        Path(__file__).resolve().parents[2] / "config" / "planner.yaml",
    ):
        if c.exists():
            return c
    raise FileNotFoundError("planner.yaml 未找到；设置 PLANNER_CONFIG 或放到 backend/config/planner.yaml")


@functools.lru_cache(maxsize=1)
def load_planner_config() -> dict[str, Any]:
    import yaml  # 懒导入，与 model_registry 一致，隔离重依赖

    return yaml.safe_load(_resolve_planner_path().read_text(encoding="utf-8")) or {}


def _classify(text: str, cfg: dict[str, Any]) -> tuple[list[str], dict[str, int]]:
    low = text.lower()
    hits: dict[str, int] = {}
    for intent, spec in cfg.get("intents", {}).items():
        n = sum(1 for kw in spec.get("keywords", []) if kw.lower() in low)
        if n:
            hits[intent] = n
    ordered = sorted(hits, key=lambda k: (-hits[k], k))  # 命中数降序，同分按名稳定
    return ordered, hits


def _score(text: str, intents: list[str], cfg: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    cx = cfg.get("complexity", {})
    low = text.lower()
    signals: dict[str, Any] = {}
    score = 0.0

    # 多步骤连接词
    conns = [c for c in cx.get("step_connectors", []) if c in text]
    pts = len(conns) * float(cx.get("step_weight", 1.0))
    score += pts
    signals["steps"] = {"hits": conns, "points": round(pts, 3)}

    # 多意图（能力）：第一个意图是主线，额外的每个加分
    extra = max(0, len(intents) - 1)
    pts = extra * float(cx.get("intent_weight", 1.5))
    score += pts
    signals["intents"] = {"count": len(intents), "points": round(pts, 3)}

    # 多输出格式：第一种之外每个加分
    outs = [o for o in cx.get("output_markers", []) if o in low]
    pts = max(0, len(outs) - 1) * float(cx.get("output_weight", 1.0))
    score += pts
    signals["outputs"] = {"hits": outs, "points": round(pts, 3)}

    # 文本长度：每超一段加分
    thr = int(cx.get("length_threshold", 120))
    chunks = max(0, (len(text) - 1) // thr) if thr > 0 else 0
    pts = chunks * float(cx.get("length_weight", 0.5))
    score += pts
    signals["length"] = {"chars": len(text), "points": round(pts, 3)}

    # 依赖/条件词
    deps = [d for d in cx.get("dependency_markers", []) if d in text]
    pts = len(deps) * float(cx.get("dependency_weight", 1.0))
    score += pts
    signals["dependencies"] = {"hits": deps, "points": round(pts, 3)}

    return round(score, 3), signals


def plan(text: str) -> Plan:
    """对一段用户输入做意图识别 + 复杂度打分（确定性、可测）。"""
    cfg = load_planner_config()
    intents, hits = _classify(text, cfg)
    max_intents = int(cfg.get("complexity", {}).get("max_intents", 3))
    intents = intents[:max_intents]
    score, signals = _score(text, intents, cfg)
    low = text.lower()
    output_formats = [o for o in cfg.get("complexity", {}).get("output_markers", []) if o in low]
    return Plan(
        text=text,
        intents=intents,
        intent_hits={k: hits[k] for k in intents},
        score=score,
        signals=signals,
        entities={"output_formats": output_formats},
    )
