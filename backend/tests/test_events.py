"""NDJSON 事件协议测试（设计文档 §15.1 / §15.3）。

验证：信封字段、seq 单调、类型化构造器字段、encode/parse round-trip、
单行 + 结尾 \\n、未登记 type 从严、/demo/stream 端到端产出可解析 NDJSON。
"""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.events import (
    Event,
    EventSequence,
    EventType,
    RunEventEmitter,
    encode_line,
    iter_ndjson,
    parse_line,
)
from app.main import app


def test_envelope_and_seq_monotonic():
    em = RunEventEmitter(run_id="r1", turn_id="t1")
    e1 = em.thinking_delta("a")
    e2 = em.content_delta("b")
    assert e1.run_id == "r1" and e1.turn_id == "t1"
    assert e2.seq == e1.seq + 1                 # seq 单调自增
    assert e1.ts > 0 and e2.ts >= e1.ts
    assert e1.type == EventType.THINKING_DELTA
    assert e1.data == {"delta": "a"}


def test_shared_sequence_across_emitters():
    seq = EventSequence(start=100)
    em_a = RunEventEmitter("r", "t", seq)
    em_b = RunEventEmitter("r", "t", seq)
    assert em_a.emit(EventType.STATUS, state="x").seq == 101
    assert em_b.emit(EventType.STATUS, state="y").seq == 102  # 跨发射器仍有序


def test_typed_constructors_fields():
    em = RunEventEmitter("r", "t")
    tcs = em.tool_call_start("t1", "web_search", {"q": 1})
    assert tcs.data == {"tool_id": "t1", "name": "web_search", "input": {"q": 1}}
    tce = em.tool_call_end("t1", "web_search", success=True, duration_ms=5)
    assert tce.type == EventType.TOOL_CALL_END and tce.data["success"] is True
    art = em.artifact("a1", "excel", "http://x", "报表.xlsx")
    assert art.type == EventType.ARTIFACT and art.data["type"] == "excel"
    src = em.source("s1", "web_url", "ref", "标题", "http://u")
    assert src.type == EventType.SOURCE and src.data["type"] == "web_url"
    qp = em.quota_paused("余额不足", balance=10, needed=100)
    assert qp.type == EventType.QUOTA_PAUSED and qp.data["needed"] == 100


def test_encode_parse_roundtrip():
    em = RunEventEmitter("r", "t")
    ev = em.observation("t1", "hello", truncated=True, total=3)
    line = encode_line(ev)
    assert line.endswith(b"\n") and line.count(b"\n") == 1   # 单行 + 结尾换行
    back = parse_line(line)
    assert back == ev


def test_parse_line_accepts_str_and_strips():
    em = RunEventEmitter("r", "t")
    ev = em.content_delta("x")
    s = encode_line(ev).decode("utf-8").strip()
    assert parse_line(s) == ev


def test_parse_line_rejects_unknown_type():
    with pytest.raises(ValidationError):
        parse_line('{"type":"not_a_real_event","run_id":"r","turn_id":"t","seq":1}')


def test_iter_ndjson_parses_back():
    em = RunEventEmitter("r", "t")
    events = [em.thinking_delta("a"), em.done()]
    lines = b"".join(iter_ndjson(iter(events)))
    parsed = [parse_line(l) for l in lines.splitlines() if l.strip()]
    assert [p.type for p in parsed] == [EventType.THINKING_DELTA, EventType.DONE]


def test_demo_stream_endpoint_ndjson():
    c = TestClient(app)
    r = c.get("/api/v1/demo/stream")
    assert r.status_code == 200
    assert "ndjson" in r.headers["content-type"]
    events = [parse_line(l) for l in r.text.splitlines() if l.strip()]
    assert len(events) >= 8
    # 首 thinking、尾 done；seq 严格递增；run_id 全程一致
    assert events[0].type == EventType.THINKING_DELTA
    assert events[-1].type == EventType.DONE
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert {e.run_id for e in events} == {"demo-run"}
    # 覆盖到协议里的主要类型
    types = {e.type for e in events}
    for must in (EventType.TOOL_CALL_START, EventType.OBSERVATION, EventType.ARTIFACT,
                 EventType.SOURCE, EventType.TASK_SUMMARY):
        assert must in types
