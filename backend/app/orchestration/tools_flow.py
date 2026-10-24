"""render_flow：把流程交给前端画。

模型只提供节点、连线和实走顺序。坐标不收，避免模型自己排版。
前端按这份结构画 SVG：实走用实线和步数角标，没走的分支用虚线。
"""
from __future__ import annotations

import json
import re
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,32}$")
_KINDS = {"rect", "diamond"}
_LANES = {"blue", "purple", "teal", "amber", "green", "red", "gray"}
_MAX_NODES = 12
_MAX_EDGES = 20


def _text(raw: Any, limit: int) -> str:
    return str(raw or "").strip()[:limit]


def _items(raw: Any) -> list[Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [raw]


def render_flow(
    title: str = "",
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    path: list[str] | None = None,
) -> dict[str, Any]:
    """校验并返回 visual。不落文件。"""
    clean_nodes: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(_items(nodes)):
        if not isinstance(item, dict):
            return {"error": f"nodes[{index}] 必须是对象，包含 id 和 label"}
        node_id = _text(item.get("id"), 32)
        label = _text(item.get("label"), 24)
        if not _ID.match(node_id):
            return {"error": f"节点 id 无效：{node_id or '（空）'}。用短英文或中文，不要空格。"}
        if node_id in seen:
            return {"error": f"节点 id 重复：{node_id}"}
        if not label:
            return {"error": f"节点 {node_id} 缺少 label"}
        kind = _text(item.get("kind") or "rect", 16) or "rect"
        if kind not in _KINDS:
            return {"error": f"节点 {node_id} 的 kind 只能是 rect 或 diamond"}
        lane = _text(item.get("lane") or "blue", 16) or "blue"
        if lane not in _LANES:
            return {"error": f"节点 {node_id} 的 lane 只能是 {'、'.join(sorted(_LANES))}"}
        seen.add(node_id)
        clean_nodes.append({"id": node_id, "label": label, "kind": kind, "lane": lane})
    if not clean_nodes:
        return {"error": "流程图至少要有一个节点"}
    if len(clean_nodes) > _MAX_NODES:
        return {"error": f"节点超过 {_MAX_NODES} 个，请拆成更短的流程"}

    clean_edges: list[dict[str, str]] = []
    for index, item in enumerate(_items(edges)):
        if not isinstance(item, dict):
            return {"error": f"edges[{index}] 必须是对象，包含 from 和 to"}
        src = _text(item.get("from"), 32)
        dst = _text(item.get("to"), 32)
        if src not in seen or dst not in seen:
            return {"error": f"连线 {src or '?'} → {dst or '?'} 指向了不存在的节点"}
        if src == dst:
            return {"error": f"节点 {src} 不能连向自己"}
        edge: dict[str, str] = {"from": src, "to": dst}
        label = _text(item.get("label"), 16)
        if label:
            edge["label"] = label
        clean_edges.append(edge)
    if len(clean_edges) > _MAX_EDGES:
        return {"error": f"连线超过 {_MAX_EDGES} 条"}

    clean_path: list[str] = []
    for item in _items(path):
        node_id = _text(item, 32)
        if not node_id:
            continue
        if node_id not in seen:
            return {"error": f"实走顺序里有不存在的节点：{node_id}"}
        if node_id not in clean_path:
            clean_path.append(node_id)
    if not clean_path:
        clean_path = [clean_nodes[0]["id"]]

    visual = {
        "kind": "flow",
        "title": _text(title, 40),
        "nodes": clean_nodes,
        "edges": clean_edges,
        "path": clean_path,
    }
    return {
        "visual": visual,
        "node_count": len(clean_nodes),
        "path": clean_path,
        "note": "流程图已交给界面绘制。回答里不要再贴坐标或图片链接，用一句话说明实走顺序即可。",
    }
