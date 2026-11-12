"""NDJSON 事件协议封装（设计文档 §15.1 / §15.3）。

多 Agent 进度可视化要发【异构事件】，NDJSON 每行一个 JSON 事件天然适配
（§12.1 结论：沿用 NDJSON 不换 SSE；边缘 Caddy 默认不缓冲，直接透传）。

本模块定义：
  · EventType —— 协议枚举（thinking_delta / content_delta / tool_call_start /
    tool_call_end / observation / status / quota_paused / artifact / source /
    error / done / task_summary）。
  · Event —— 信封（type / run_id / turn_id / seq / ts + data 业务体）；
    前端按 seq 排序、按 run 分组折叠（§15.1）。
  · EventSequence —— 每个 run 的单调自增序号，保证跨副本合并后仍有序。
  · RunEventEmitter —— 一次 run 的发射器，自动填 run_id/turn_id/seq/ts，
    并对每个事件类型给类型化构造器（协议自文档、字段可测）。
  · encode_line / parse_line —— 一行一个事件、以 \\n 结尾；残行留给前端缓冲区（§15.2）。
    orjson（快）序列化，缺则回退标准 json（测试轻量环境可用）。

纪律：后端保证每步都推事件；`data` 里业务字段由各构造器固化，不散落魔法键。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from enum import Enum
from typing import Any, AsyncIterator, Iterator

from pydantic import BaseModel, Field


class EventType(str, Enum):
    THINKING_DELTA = "thinking_delta"
    CONTENT_DELTA = "content_delta"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    OBSERVATION = "observation"
    STATUS = "status"
    QUOTA_PAUSED = "quota_paused"
    ARTIFACT = "artifact"
    SOURCE = "source"
    ERROR = "error"
    DONE = "done"
    TASK_SUMMARY = "task_summary"
    CONTEXT_USAGE = "context_usage"
    VISUAL = "visual"
    ASK_USER = "ask_user"


class Event(BaseModel):
    """事件信封。seq 由 EventSequence 自增；ts 为毫秒时间戳。

    v2.2.0-p1.2（Phase A3 / Event 契约 v1）：补 trace_id / tenant_id / payload 三字段，
    成为两项目共用的事件契约（8/8 字段齐）：
    - `trace_id`：跨 run / 跨服务的链路追踪 ID（Phase B2 网关入口注入，缺省空）；
    - `tenant_id`：租户标识（当前单租户预留，Phase B2 注入）；
    - `payload`：**横切元数据载荷**（归因 / 计量 / step_id 等），与 `data` 的分工——
      data=业务体（前端消费），payload=横切层（事件流合并与审计消费），互不混放。
    三字段全缺省（空串/空 dict）：老 NDJSON 行解析回来自动补缺省（向后兼容），
    新事件序列化会带上空缺省值（前端按未知字段忽略，协议显式化）。
    """

    type: EventType
    run_id: str
    turn_id: str
    seq: int
    ts: int = Field(default_factory=lambda: int(time.time() * 1000))
    trace_id: str = ""
    tenant_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class EventSequence:
    """每个 run 一个单调自增 seq。

    p4.3b：加锁——并行子任务（层内 ThreadPoolExecutor）会并发调 next()，
    无锁的 `self._n += 1` 读-改-写竞争会产生重复 seq（前端按 seq 排序会乱）。
    """

    def __init__(self, start: int = 0) -> None:
        self._n = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._n += 1
            return self._n


class RunEventEmitter:
    """一次 run 的事件发射器：自动填 run_id/turn_id/seq，产出 Event。

    v2.2.0-p1.2：构造可带 trace_id / tenant_id / payload（横切元数据，入口注入
    一次、全事件携带，Phase B2 网关注入时用）；也可运行期补设属性。
    不给 emit() 开 per-event payload 传参口——「payload」与 visual 等构造器的
    data 业务键撞名，且归因元数据本来就是 run 级一致，统一走 emitter 注入。
    """

    def __init__(
        self,
        run_id: str,
        turn_id: str,
        seq: EventSequence | None = None,
        *,
        trace_id: str = "",
        tenant_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.turn_id = turn_id
        self.trace_id = trace_id
        self.tenant_id = tenant_id
        self.default_payload: dict[str, Any] = dict(payload or {})
        self._seq = seq or EventSequence()

    # ---- 基础发射 ----
    def emit(self, type_: EventType, **data: Any) -> Event:
        return Event(
            type=type_,
            run_id=self.run_id,
            turn_id=self.turn_id,
            seq=self._seq.next(),
            trace_id=self.trace_id,
            tenant_id=self.tenant_id,
            payload=dict(self.default_payload),
            data=data,
        )

    # ---- 类型化构造器（协议字段固化，§15.1）----
    def thinking_delta(self, delta: str) -> Event:
        return self.emit(EventType.THINKING_DELTA, delta=delta)

    def content_delta(self, delta: str) -> Event:
        return self.emit(EventType.CONTENT_DELTA, delta=delta)

    def tool_call_start(self, tool_id: str, name: str, input: dict[str, Any]) -> Event:
        return self.emit(EventType.TOOL_CALL_START, tool_id=tool_id, name=name, input=input)

    def tool_call_end(
        self,
        tool_id: str,
        name: str,
        *,
        success: bool = True,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> Event:
        return self.emit(
            EventType.TOOL_CALL_END,
            tool_id=tool_id,
            name=name,
            success=success,
            duration_ms=duration_ms,
            error=error,
        )

    def observation(self, tool_id: str, text: str, *, truncated: bool = False, total: int | None = None) -> Event:
        return self.emit(
            EventType.OBSERVATION, tool_id=tool_id, text=text, truncated=truncated, total=total
        )

    def status(self, agent: str, state: str, subtask_id: str | None = None) -> Event:
        return self.emit(EventType.STATUS, agent=agent, state=state, subtask_id=subtask_id)

    def quota_paused(self, reason: str, balance: int, needed: int) -> Event:
        return self.emit(EventType.QUOTA_PAUSED, reason=reason, balance=balance, needed=needed)

    def ask_user(self, questions: list[dict[str, Any]]) -> Event:
        """2.1.0 P1-1 HITL：模型请求用户补充输入（任务随即进入 paused_input）。
        questions 为归一化数组（每项 question/options/need_file/file_hint），前端按 n/N 逐题收集。"""
        return self.emit(EventType.ASK_USER, questions=questions)

    def artifact(self, asset_id: str, type: str, storage_url: str, name: str | None = None) -> Event:
        return self.emit(
            EventType.ARTIFACT,
            asset_id=asset_id,
            type=type,
            storage_url=storage_url,
            name=name,
        )

    def source(self, source_id: str, type: str, ref: str, title: str, url: str) -> Event:
        return self.emit(
            EventType.SOURCE,
            source_id=source_id,
            type=type,
            ref=ref,
            title=title,
            url=url,
        )

    def error(self, message: str, code: str | None = None) -> Event:
        return self.emit(EventType.ERROR, message=message, code=code)

    def context_usage(self, window: int, used: int, items: list[dict[str, Any]]) -> Event:
        return self.emit(EventType.CONTEXT_USAGE, window=window, used=used, items=items)

    def visual(self, kind: str, payload: dict[str, Any]) -> Event:
        """前端绘制用的结构。kind=flow 是流程图，kind=chart 是 ECharts 数据。

        注意：这里的 payload 是 **data 业务键**（进 data.payload），与信封层的
        横切 payload（Event.payload）同名不同层，勿混。
        """
        return self.emit(EventType.VISUAL, kind=kind, payload=payload)

    def task_summary(self, artifacts: list[dict[str, Any]], sources: list[dict[str, Any]]) -> Event:
        return self.emit(EventType.TASK_SUMMARY, artifacts=artifacts, sources=sources)

    def done(
        self,
        status: str = "done",
        *,
        tokens_used: int | None = None,
        model: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        prompt_tokens: int | None = None,
        cache_hit_tokens: int | None = None,
    ) -> Event:
        """收尾。tokens_used / model / steps（逐步用量明细）可选，供前端回复行展示；不传则不进 data。"""
        extra: dict[str, Any] = {}
        if tokens_used is not None:
            extra["tokens_used"] = int(tokens_used)
        if model:
            extra["model"] = model
        if steps:
            extra["steps"] = steps
        if prompt_tokens is not None and prompt_tokens > 0:
            extra["prompt_tokens"] = int(prompt_tokens)
        if cache_hit_tokens is not None and cache_hit_tokens > 0:
            extra["cache_hit_tokens"] = int(cache_hit_tokens)  # 2.1.0：缓存命中率展示
        return self.emit(EventType.DONE, status=status, **extra)


# ---- 序列化 / 反序列化 ----


def _dumps(obj: Any) -> bytes:
    try:
        import orjson  # 懒导入：requirements 有；测试轻量环境缺则回退标准库

        return orjson.dumps(obj)
    except ModuleNotFoundError:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def encode_line(event: Event) -> bytes:
    """序列化为一行 NDJSON（含结尾 \\n）。"""
    return _dumps(event.model_dump(mode="json")) + b"\n"


def parse_line(line: bytes | str) -> Event:
    """解析一行 NDJSON 回 Event（消费者 / 测试 round-trip）。

    未登记的 type 会抛 ValidationError——协议从严，前端不认识的事件宁可不认。
    """
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    return Event.model_validate_json(line.strip())


def new_run_id() -> str:
    return uuid.uuid4().hex[:16]


async def to_ndjson_bytes(events: AsyncIterator[Event]) -> AsyncIterator[bytes]:
    """异步事件流 → NDJSON 字节流（供 FastAPI StreamingResponse）。"""
    async for ev in events:
        yield encode_line(ev)


def iter_ndjson(events: Iterator[Event]) -> Iterator[bytes]:
    """同步事件迭代器 → NDJSON 字节流（便于测试 / 非异步场景）。"""
    for ev in events:
        yield encode_line(ev)
