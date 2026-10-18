"""LangGraph 编排骨架测试（p3.1）：路由真正驱动控制流 + NDJSON 事件单调有序。"""
from app.core.events import EventType, parse_line
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


def test_events_roundtrip_through_ndjson():
    _result, events = run_task("画一个柱状图看板")
    for ev in events:
        assert parse_line(__import__("json").dumps(ev.model_dump(mode="json"))) is not None
