"""管理端运行溯源：从任务行和助手 trace 拼一份只读摘要。

trace 缺失就如实返回空序列，不编造工具调用。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


def load_events(conn: Connection, task_id: str) -> list[dict[str, Any]]:
    try:
        row = conn.execute(
            text(
                "SELECT trace FROM message WHERE role = 'assistant' AND trace LIKE :k "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"k": f"%{task_id}%"},
        ).first()
    except Exception:  # noqa: BLE001 - 旧库没有 message 表时，溯源按「无 trace」返回
        return []
    if not row or not row[0]:
        return []
    try:
        data = json.loads(row[0])
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def summarize(events: list[dict[str, Any]], *, request: dict[str, Any] | None = None) -> dict[str, Any]:
    tools: list[str] = []
    artifacts: list[str] = []
    validation_note = ""
    rag_office_user = ""
    rag_username = ""
    identity_mismatch = False
    intents: list[str] = []
    route = ""
    agents_order: list[str] = []  # p5.8：状态事件里的 Agent 链（保序去重）
    subtask_agents: list[dict[str, str]] = []  # p5.8：multi 子任务 → 执行 Agent
    subtask_seen: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("type") or "")
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if kind == "tool_call_start":
            name = str(data.get("name") or "")
            if name:
                tools.append(name)
        elif kind == "artifact":
            label = str(data.get("name") or data.get("asset_id") or "")
            if label:
                artifacts.append(label)
        elif kind == "observation":
            text_value = str(data.get("text") or "")
            if "result_validator" in text_value or "未在工具观察" in text_value:
                validation_note = text_value[:240]
            if "identity_mismatch" in text_value:
                identity_mismatch = "true" in text_value.lower()
            if "office_username=" in text_value:
                rag_office_user = _after(text_value, "office_username=")
            if "rag_username=" in text_value:
                rag_username = _after(text_value, "rag_username=")
        elif kind == "thinking_delta":
            line = str(data.get("delta") or data.get("text") or "")
            if line.startswith("识别意图"):
                intents.append(line[:120])
        elif kind == "status":
            agent = str(data.get("agent") or "")
            if agent and agents_order[-1:] != [agent]:
                agents_order.append(agent)
            sid = str(data.get("subtask_id") or "")
            if sid and agent and sid not in subtask_seen:
                subtask_seen.add(sid)
                subtask_agents.append({"id": sid, "agent": agent})
        elif kind == "done":
            route = str(data.get("status") or route)
    req = request or {}
    return {
        "tools": tools,
        "tool_summary": " → ".join(tools) if tools else "",
        "tool_steps": len(tools),
        "artifacts": artifacts,
        "has_artifact": bool(artifacts),
        "rag_called": "rag_retrieve" in tools,
        "validation_mismatch": bool(validation_note),
        "validation_note": validation_note,
        "rag_username": rag_username,
        "office_username": rag_office_user or str(req.get("office_username") or ""),
        "identity_mismatch": identity_mismatch or bool(
            rag_username and rag_office_user and rag_username != rag_office_user
        ),
        "intents": intents[:3],
        "route": route,
        "mode": route,
        "agents": agents_order,
        "subtasks": subtask_agents,
        "model": str(req.get("model") or ""),
        "has_trace": bool(events),
        "duration_ms": duration_ms(events),
        "flow": build_flow(events, request=req),
    }


def duration_ms(events: list[dict[str, Any]]) -> int | None:
    stamps = [int(ev["ts"]) for ev in events if isinstance(ev, dict) and ev.get("ts")]
    if len(stamps) < 2:
        return None
    return max(0, max(stamps) - min(stamps))


# 管理端「实走路径」状态机：节点/边由后端定义，path 由事件派生，前端只渲染。
FLOW_NODES: list[dict[str, Any]] = [
    {"key": "received", "label": "收到问题", "kind": "rect", "color": "blue"},
    {"key": "quota_check", "label": "额度检查？", "kind": "diamond", "color": "blue"},
    {"key": "quota_paused", "label": "配额不足", "kind": "rect", "color": "red", "terminal": True},
    {"key": "plan", "label": "意图规划", "kind": "rect", "color": "purple"},
    {"key": "route", "label": "路由？", "kind": "diamond", "color": "purple"},
    {"key": "chitchat", "label": "直答应答", "kind": "rect", "color": "gray", "terminal": True},
    {"key": "tools", "label": "工具执行", "kind": "rect", "color": "teal"},
    {"key": "retrieve", "label": "检索知识库", "kind": "rect", "color": "teal"},
    {"key": "validate", "label": "数字校验？", "kind": "diamond", "color": "amber"},
    {"key": "mismatch", "label": "数字未对齐", "kind": "rect", "color": "amber", "terminal": True},
    {"key": "generate", "label": "生成回答", "kind": "rect", "color": "green"},
    {"key": "done", "label": "任务完成", "kind": "rect", "color": "green", "terminal": True},
    {"key": "error", "label": "出错暂停", "kind": "rect", "color": "red", "terminal": True},
]

FLOW_EDGES: list[dict[str, Any]] = [
    {"from": "received", "to": "quota_check"},
    {"from": "quota_check", "to": "quota_paused", "label": "不足"},
    {"from": "quota_check", "to": "plan", "label": "通过"},
    {"from": "plan", "to": "route"},
    {"from": "route", "to": "chitchat", "label": "直答"},
    {"from": "route", "to": "tools", "label": "需工具"},
    {"from": "tools", "to": "retrieve", "label": "检索"},
    {"from": "retrieve", "to": "validate"},
    {"from": "tools", "to": "validate", "label": "无检索"},
    {"from": "tools", "to": "error", "label": "出错"},
    {"from": "validate", "to": "mismatch", "label": "未对齐"},
    {"from": "validate", "to": "generate", "label": "通过"},
    {"from": "generate", "to": "done"},
]


def derive_flow_path(events: list[dict[str, Any]]) -> tuple[list[str], list[str], dict[str, str]]:
    """从 trace 事件推出本次实走节点序列 + 旁路高亮。"""
    tools: list[str] = []
    has_intent = False
    has_quota = False
    has_error = False
    has_done = False
    has_validation = False
    is_chitchat = False
    details: dict[str, str] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("type") or "")
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if kind == "thinking_delta":
            line = str(data.get("delta") or data.get("text") or "")
            if line.startswith("识别意图"):
                has_intent = True
                details["plan"] = line[:160]
                if "闲聊" in line:
                    is_chitchat = True
        elif kind == "tool_call_start":
            name = str(data.get("name") or "tool")
            if name:
                tools.append(name)
        elif kind == "quota_paused":
            has_quota = True
        elif kind == "error":
            has_error = True
            details["error"] = str(data.get("message") or "")[:160]
        elif kind == "done":
            has_done = True
            status = str(data.get("status") or "done")
            if status.startswith("paused_insufficient") or status == "quota":
                has_quota = True
            if "error" in status or status == "failed":
                has_error = True
        elif kind == "observation":
            text_value = str(data.get("text") or "")
            if "result_validator" in text_value or "未在工具观察" in text_value:
                has_validation = True
                details["validate"] = text_value[:160]
    if not events:
        return ["received"], [], details

    path = ["received", "quota_check"]
    if has_quota:
        path.append("quota_paused")
        return path, [], details
    path.append("plan")
    path.append("route")
    if tools:
        path.append("tools")
        details["tools"] = " → ".join(tools)
        if has_error and not has_done:
            path.append("error")
            return path, [], details
        if "rag_retrieve" in tools:
            path.append("retrieve")
        path.append("validate")
        marks = ["mismatch"] if has_validation else []
        if has_error:
            path.append("error")
            return path, marks, details
        path.append("generate")
        path.append("done")
        return path, marks, details
    if is_chitchat:
        path.append("chitchat")
        return path, [], details
    if has_error:
        path.append("error")
        return path, [], details
    if has_intent or has_done:
        path.append("generate")
        path.append("done")
    return path, [], details


def build_flow(events: list[dict[str, Any]], *, request: dict[str, Any] | None = None) -> dict[str, Any]:
    """把一次任务的事件收成管理端状态机（flow_path 由后端派生，前端不推分支）。"""
    req = request or {}
    path, marks, details = derive_flow_path(events)
    nodes = []
    for node in FLOW_NODES:
        item = dict(node)
        if details.get(node["key"]):
            item["detail"] = details[node["key"]]
        nodes.append(item)
    return {
        "question": str(req.get("text") or req.get("question") or ""),
        "nodes": nodes,
        "edges": list(FLOW_EDGES),
        "path": path,
        "flow_path": path,
        "marks": marks,
        "events": _compact_events(events),
    }


def _compact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("type") or "")
        if kind in {"thinking_delta", "content_delta"}:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        slim = {k: data[k] for k in ("name", "text", "status", "message", "agent", "state") if data.get(k) not in (None, "")}
        if "text" in slim:
            slim["text"] = str(slim["text"])[:240]
        out.append({"type": kind, "ts": ev.get("ts"), "seq": ev.get("seq"), "data": slim})
        if len(out) >= 80:
            break
    return out


def _after(text_value: str, key: str) -> str:
    start = text_value.find(key)
    if start < 0:
        return ""
    rest = text_value[start + len(key) :]
    end = len(rest)
    for mark in ("；", ",", " ", "}", "\n"):
        pos = rest.find(mark)
        if pos >= 0:
            end = min(end, pos)
    return rest[:end].strip().strip('"')
