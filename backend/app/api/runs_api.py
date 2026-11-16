"""事件流回放（v2.2.0-p1.11 / Phase D）——GET /runs/{run_id}/replay。

四套日志按 run_id 合一（B2 的 trace_id=run_id 是钥匙）：
  · events      —— message.trace 里该 run 的全部编排事件（B2 起逐事件带 run_id）
  · tools       —— tool_invocation（C1 幂等表：工具执行与观察）+ tool_call_log（旧日志）
  · usage       —— token_ledger（task_id=run_id 的预扣/结算流水）
  · dead_letter —— audit_log 里 run.dead_letter 死信（C2）
前端/排查任取一角；全程只读。

权限：本人（session 归属）或 admin。run 不存在 → 404（不区分权限归属，避免探测）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter()


def _rows(conn, sql: str, params: dict) -> list[dict[str, Any]]:
    return [dict(m) for m in conn.execute(text(sql), params).mappings()]


def _safe_rows(
    conn, sql: str, params: dict, *, label: str, degraded: list[str]
) -> list[dict[str, Any]]:
    """查询失败（缺表/缺列）时降级为空列表，不把整个回放打成 500。

    为什么宽容（v2.3.0-p1.4）：回放是排障工具，能给的先给。真事故（2026-11-17）——
    本地库漏了 0014 迁移（`tool_invocation` 不存在），replay 直接 500，反而把最有用的
    events 一起挡在门外，排障的人连事件都看不到。少一格数据远好过整页报错。
    """
    try:
        return _rows(conn, sql, params)
    except Exception:  # noqa: BLE001 - 排障工具宁可少一格，也不整页失败
        logger.warning("回放查询失败，该项降级为空 | %s", label, exc_info=True)
        degraded.append(label)
        return []


@router.get("/runs/{run_id}/replay")
async def replay_run(run_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo
    from .routes import _current_user

    user = _current_user(authorization)  # fail-closed

    engine = get_engine()
    with engine.connect() as conn:
        task_rows = _rows(
            conn,
            "SELECT id, session_id, status, text, result, tokens_used, pause_reason, "
            "pause_payload, retry_of, request_json, created_at FROM task WHERE id=:r",
            {"r": run_id},
        )
        if not task_rows:
            raise HTTPException(404, detail={"code": "RUN_NOT_FOUND", "message": f"任务不存在：{run_id}"})
        task = task_rows[0]
        session_id = task["session_id"]

    repo = SessionRepo(engine)
    role = str(user.get("role") or "")
    if role not in ("admin", "superadmin") and not repo.session_belongs_to(session_id, user["id"]):
        # 与会话权限同口径：非本人且非管理员 → 404（不暴露存在性）
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND", "message": f"任务不存在：{run_id}"})

    events: list[dict[str, Any]] = []
    with engine.connect() as conn:
        msg_rows = _rows(
            conn,
            "SELECT trace FROM message WHERE session_id=:s AND trace IS NOT NULL ORDER BY id",
            {"s": session_id},
        )
    for m in msg_rows:
        try:
            batch = json.loads(m["trace"] or "[]")
        except ValueError:
            continue
        if not isinstance(batch, list):
            continue
        for ev in batch:
            if isinstance(ev, dict) and str(ev.get("run_id") or "") == run_id:
                events.append(ev)

    degraded: list[str] = []
    with engine.connect() as conn:
        invocations = _safe_rows(
            conn,
            "SELECT tool_name, args_preview, observation, created_at FROM tool_invocation "
            "WHERE run_id=:r ORDER BY id",
            {"r": run_id},
            label="tools.invocations",
            degraded=degraded,
        )
        call_log = _safe_rows(
            conn,
            "SELECT tool, params, error, success FROM tool_call_log "
            "WHERE agent_run_id=:r ORDER BY id",
            {"r": run_id},
            label="tools.call_log",
            degraded=degraded,
        )
        ledger = _safe_rows(
            conn,
            "SELECT model, reserve, settle, kind, created_at FROM token_ledger "
            "WHERE task_id=:r ORDER BY id",
            {"r": run_id},
            label="usage",
            degraded=degraded,
        )
        dead_letter = _safe_rows(
            conn,
            "SELECT actor_username, action, detail, created_at FROM audit_log "
            "WHERE action='run.dead_letter' AND target_id=:r ORDER BY id",
            {"r": run_id},
            label="dead_letter",
            degraded=degraded,
        )

    request_meta: Any = None
    try:
        request_meta = json.loads(task["request_json"]) if task["request_json"] else None
    except ValueError:
        request_meta = None
    pause_payload: Any = None
    try:
        pause_payload = json.loads(task["pause_payload"]) if task["pause_payload"] else None
    except ValueError:
        pause_payload = None

    return {
        "run": {
            "run_id": task["id"],
            "session_id": session_id,
            "status": task["status"],
            "text": task["text"],
            "result": task["result"],
            "tokens_used": task["tokens_used"],
            "pause_reason": task["pause_reason"],
            "pause_payload": pause_payload,
            "retry_of": task["retry_of"],
            "request": request_meta,
            "created_at": str(task["created_at"]),
        },
        "events": events,
        "tools": {"invocations": invocations, "call_log": call_log},
        "usage": ledger,
        "dead_letter": dead_letter,
        # v2.3.0-p1.4：哪些块因缺表/缺列被降级（空列表 = 全部正常）
        "degraded": degraded,
    }
