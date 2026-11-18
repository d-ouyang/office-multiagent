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


def test_done_carries_optional_usage():
    em = RunEventEmitter("r", "t")
    ev = em.done("single", tokens_used=12, model="deepseek-chat")
    assert ev.data["status"] == "single"
    assert ev.data["tokens_used"] == 12
    assert ev.data["model"] == "deepseek-chat"
    bare = em.done()
    assert "tokens_used" not in bare.data
    assert "model" not in bare.data


def test_event_sequence_thread_safe_no_duplicates():
    # p4.3b：层内并行子任务并发调 next()——无锁读-改-写会产生重复 seq（前端按 seq 排序会乱）
    import threading

    seq = EventSequence()
    collected: list[int] = []
    guard = threading.Lock()

    def worker():
        vals = [seq.next() for _ in range(200)]
        with guard:
            collected.extend(vals)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(collected) == 1600
    assert len(set(collected)) == 1600          # 无重复
    assert sorted(collected) == list(range(1, 1601))  # 无跳号无重号


# --------------------------------------------------------------------------- #
# v2.2.0-p1.2（Phase A3）：Event 契约 v1——补 trace_id / tenant_id / payload
# --------------------------------------------------------------------------- #


def test_event_contract_defaults_are_backward_compatible():
    """新字段全缺省：老构造路径（无 trace/tenant）行为不变。"""
    em = RunEventEmitter("r", "t")
    ev = em.content_delta("hi")
    assert ev.trace_id == "" and ev.tenant_id == "" and ev.payload == {}


def test_emitter_injects_trace_and_tenant_into_every_event():
    em = RunEventEmitter("r", "t", trace_id="tr-1", tenant_id="tn-1")
    evs = [em.status("agent", "start"), em.content_delta("x"), em.done()]
    for ev in evs:
        assert ev.trace_id == "tr-1" and ev.tenant_id == "tn-1"


def test_emitter_default_payload_carried_and_not_shared():
    em = RunEventEmitter("r", "t", payload={"feature": "chat", "step_id": "s-0"})
    ev1, ev2 = em.observation("t1", "o"), em.observation("t2", "o")
    assert ev1.payload == ev2.payload == {"feature": "chat", "step_id": "s-0"}
    ev1.payload["mutated"] = True  # 浅拷贝：单事件突变不污染其他事件
    assert "mutated" not in ev2.payload


def test_roundtrip_keeps_contract_fields():
    em = RunEventEmitter("r", "t", trace_id="tr-9", tenant_id="tn-9", payload={"k": "v"})
    ev = em.done(status="done", tokens_used=5)
    back = parse_line(encode_line(ev))
    assert back.trace_id == "tr-9" and back.tenant_id == "tn-9"
    assert back.payload == {"k": "v"}


def test_old_ndjson_line_without_new_fields_still_parses():
    """向后兼容判据：v2.1.0 时代的事件行（无 trace_id/payload 键）能解析回 Event。"""
    legacy = '{"type":"content_delta","run_id":"r","turn_id":"t","seq":3,"ts":1790000000000,"data":{"delta":"x"}}'
    ev = parse_line(legacy)
    assert ev.type.value == "content_delta" and ev.data["delta"] == "x"
    assert ev.trace_id == "" and ev.payload == {}


def test_visual_data_payload_unchanged():
    """visual 的 data.payload（业务键）不因信封 payload 出现而漂移。"""
    em = RunEventEmitter("r", "t", payload={"attribution": "gateway"})
    ev = em.visual("chart", {"x": [1, 2]})
    assert ev.data["kind"] == "chart" and ev.data["payload"] == {"x": [1, 2]}
    assert ev.payload == {"attribution": "gateway"}  # 同名不同层
