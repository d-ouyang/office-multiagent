"""LangGraph 编排骨架测试（p3.1）：路由真正驱动控制流 + NDJSON 事件单调有序。"""
from fastapi.testclient import TestClient

from app.core.events import EventType, parse_line
from app.main import app
from app.orchestration.graph import run_task


def test_simple_input_routes_single():
    result, events = run_task("帮我查一下上个季度的销售汇总")
    assert result["route"] == "single"
    types = [e.type for e in events]
    assert EventType.STATUS in types
    assert types[-1] == EventType.DONE
    # seq 单调不重复（跨节点共享 emitter）
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert {e.run_id for e in events} == {result["run_id"]}


def test_complex_input_routes_multi():
    result, events = run_task("先分析销售数据，然后基于分析结果生成报表，同时导出 excel 和 pdf")
    assert result["route"] == "multi"
    assert any(
        e.type == EventType.STATUS and e.data.get("agent") == "orchestrator" for e in events
    )
    # p3.2：复杂任务带子任务 DAG
    dag = result["dag"]
    assert dag and len(dag["subtasks"]) >= 2
    assert dag["topo_order"]  # 拓扑序非空


def test_events_roundtrip_through_ndjson():
    _result, events = run_task("画一个柱状图看板")
    for ev in events:
        assert parse_line(__import__("json").dumps(ev.model_dump(mode="json"))) is not None


def test_tasks_endpoint_streams_ndjson():
    # 真实 HTTP 层回归：/tasks 必须逐行吐出 NDJSON（曾漏 import encode_line 被实跑抓到）
    c = TestClient(app)
    r = c.post("/api/v1/tasks", json={"text": "先清洗，再分析，再出报表"})
    assert r.status_code == 200
    assert "ndjson" in r.headers["content-type"]
    events = [parse_line(l) for l in r.text.splitlines() if l.strip()]
    assert events and events[-1].type == EventType.DONE
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
