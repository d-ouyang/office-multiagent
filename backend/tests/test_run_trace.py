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


def test_summarize_mode_agents_subtasks():
    # p5.8：任务监控体现 执行模式 / Agent 链 / multi 子任务→Agent 归属。
    from app.core.run_trace import summarize

    events = [
        {"type": "status", "data": {"agent": "planner", "state": "done", "subtask_id": None}},
        {"type": "status", "data": {"agent": "orchestrator", "state": "running", "subtask_id": None}},
        {"type": "status", "data": {"agent": "data_cleaning", "state": "running", "subtask_id": "cleaning"}},
        {"type": "status", "data": {"agent": "data_cleaning", "state": "done", "subtask_id": "cleaning"}},
        {"type": "status", "data": {"agent": "data_analysis", "state": "running", "subtask_id": "analysis"}},
        {"type": "tool_call_start", "data": {"name": "query_orders"}},
        {"type": "status", "data": {"agent": "data_analysis", "state": "done", "subtask_id": "analysis"}},
        {"type": "done", "data": {"status": "multi"}},
    ]
    s = summarize(events, request={"text": "清洗并分析"})
    assert s["mode"] == "multi"
    # 保序去重：planner → orchestrator → data_cleaning → data_analysis
    assert s["agents"] == ["planner", "orchestrator", "data_cleaning", "data_analysis"]
    assert s["subtasks"] == [
        {"id": "cleaning", "agent": "data_cleaning"},
        {"id": "analysis", "agent": "data_analysis"},
    ]
    assert s["tools"] == ["query_orders"]


def test_summarize_single_mode_agents():
    from app.core.run_trace import summarize

    events = [
        {"type": "status", "data": {"agent": "planner", "state": "done", "subtask_id": None}},
        {"type": "status", "data": {"agent": "general", "state": "running", "subtask_id": None}},
        {"type": "status", "data": {"agent": "general", "state": "running", "subtask_id": None}},
        {"type": "done", "data": {"status": "single"}},
    ]
    s = summarize(events)
    assert s["mode"] == "single"
    assert s["agents"] == ["planner", "general"]  # 连续同名去重
    assert s["subtasks"] == []
