"""管理端实走路径：flow_path 由后端按状态机派生。"""
from app.core.run_trace import build_flow, derive_flow_path


def test_empty_trace_only_received():
    path, marks, _ = derive_flow_path([])
    assert path == ["received"]
    assert marks == []


def test_quota_paused_stops_at_terminal():
    path, marks, _ = derive_flow_path([{"type": "quota_paused"}])
    assert path == ["received", "quota_check", "quota_paused"]
    assert marks == []


def test_tool_and_rag_path():
    events = [
        {"type": "thinking_delta", "data": {"delta": "识别意图：查数"}},
        {"type": "tool_call_start", "data": {"name": "query_orders"}},
        {"type": "tool_call_start", "data": {"name": "rag_retrieve"}},
        {"type": "observation", "data": {"text": "结果校验：终答中的数字 9999 未在工具观察"}},
        {"type": "done", "data": {"status": "done"}},
    ]
    path, marks, details = derive_flow_path(events)
    assert path == [
        "received",
        "quota_check",
        "plan",
        "route",
        "tools",
        "retrieve",
        "validate",
        "generate",
        "done",
    ]
    assert marks == ["mismatch"]
    assert "query_orders" in details["tools"]
    flow = build_flow(events, request={"text": "查订单"})
    assert flow["flow_path"] == path
    assert flow["question"] == "查订单"
    assert {n["key"] for n in flow["nodes"]} >= {"received", "tools", "done"}


def test_chitchat_path():
    path, marks, _ = derive_flow_path(
        [
            {"type": "thinking_delta", "data": {"delta": "识别意图：闲聊"}},
            {"type": "done", "data": {"status": "done"}},
        ]
    )
    assert path == ["received", "quota_check", "plan", "route", "chitchat"]
    assert marks == []
