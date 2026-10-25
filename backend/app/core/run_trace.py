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


def build_flow(events: list[dict[str, Any]], *, request: dict[str, Any] | None = None) -> dict[str, Any]:
    """把一次任务的事件收成管理端 Q→A 节点流（参考 RAG 问答溯源，不复刻其状态机）。"""
    req = request or {}
    nodes: list[dict[str, Any]] = [
        {"key": "received", "label": "收到问题", "kind": "start"},
    ]
    path = ["received"]
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("type") or "")
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if kind == "thinking_delta":
            line = str(data.get("delta") or data.get("text") or "")
            if line.startswith("识别意图") and "intent" not in path:
                nodes.append({"key": "intent", "label": "意图识别", "kind": "decision", "detail": line[:160]})
                path.append("intent")
        elif kind == "tool_call_start":
            name = str(data.get("name") or "tool")
            key = f"tool:{name}:{sum(1 for item in path if item.startswith('tool:'))}"
            nodes.append({"key": key, "label": name, "kind": "tool"})
            path.append(key)
        elif kind == "artifact":
            label = str(data.get("name") or data.get("asset_id") or "产物")
            key = f"artifact:{label}"
            if key not in path:
                nodes.append({"key": key, "label": f"产物 {label}", "kind": "artifact"})
                path.append(key)
        elif kind == "quota_paused" and "quota" not in path:
            nodes.append({"key": "quota", "label": "配额不足", "kind": "terminal"})
            path.append("quota")
        elif kind == "error" and "error" not in path:
            nodes.append({"key": "error", "label": "出错", "kind": "terminal", "detail": str(data.get("message") or "")[:160]})
            path.append("error")
        elif kind == "done":
            status = str(data.get("status") or "done")
            key = f"done:{status}"
            if key not in path:
                nodes.append({"key": key, "label": status, "kind": "terminal"})
                path.append(key)
    if not any(n["kind"] == "terminal" for n in nodes):
        nodes.append({"key": "answer", "label": "生成回答", "kind": "answer"})
        path.append("answer")
    return {
        "question": str(req.get("text") or req.get("question") or ""),
        "nodes": nodes,
        "path": path,
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
