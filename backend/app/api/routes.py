"""API 路由：/health 联动探测、/models 模型注册表、/plan 规划路由、/internal/auth/ping 内部鉴权自检、/demo/stream NDJSON 示例。"""
import re

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from typing import Any

from ..core import chroma_client, db, redis_client
from ..core.config import settings
from ..core.events import EventType, RunEventEmitter, encode_line, iter_ndjson, new_run_id
from ..core.internal_auth import require_internal
from ..core.decomposer import decompose
from ..core.model_registry import get_dialogue_models
from ..core.planner import plan as make_plan
from ..core.router import decide

router = APIRouter()


@router.get("/health")
def health():
    my_ok, my_err = db.ping_mysql()
    rd_ok, rd_err = redis_client.ping_redis()
    ch_ok, ch_err = chroma_client.ping_chroma()

    services = {
        "mysql": {"ok": my_ok, "detail": my_err},
        "redis": {"ok": rd_ok, "detail": rd_err},
        "chroma": {"ok": ch_ok, "detail": ch_err},
    }

    # chroma 缺失不致命（REQUIRE_CHROMA=false 时）；mysql/redis 缺失=降级
    required = [v for k, v in services.items() if k != "chroma" or settings.require_chroma]
    all_ok = all(v["ok"] for v in required)

    return {
        "status": "ok" if all_ok else "degraded",
        "services": services,
    }


@router.get("/models")
def models(pool: list[str] | None = Query(default=None, description="按模型池过滤")):
    """对话下拉可见模型（§十七.1 字段）。"""
    return {"models": get_dialogue_models(pool)}


class PlanRequest(BaseModel):
    text: str


@router.post("/plan")
def plan_endpoint(body: PlanRequest):
    """意图识别 + 复杂度打分 + 路由决策（§四.2/§四.3，确定性规则，可测）。"""
    p = make_plan(body.text)
    d = decide(p)
    out = {
        "intent": p.intents[0] if p.intents else "general",
        "intents": p.intents,
        "score": p.score,
        "route": d.mode,
        "reason": d.reason,
        "primary_agent": d.primary_agent,
        "signals": p.signals,
        "entities": p.entities,
    }
    if d.mode == "multi":
        out["dag"] = decompose(p).to_dict()  # 复杂任务给子任务 DAG（p3.2）
    return out


class TaskRequest(BaseModel):
    text: str
    user_id: int | None = None   # 提供则走 token 池 reserve/settle（§十四）
    estimate: int = 0            # 本次任务 token 预扣估算
    session_id: str | None = None  # p6.2c：会话 id（不传则按登录身份自动新建）
    model: str | None = None     # p6.5：本次任务使用的对话模型（注册表 id；不传用会话/默认）
    attachments: list[str] | None = None  # p6.12：随消息附件（文档目录内相对路径，如 "dev/报告.md"）
    effort: str | None = None    # low/medium/high/max；非推理模型忽略，不 400


class UpdateSessionRequest(BaseModel):
    model: str | None = None     # p6.5：更新会话默认模型
    title: str | None = None
    pinned: bool | None = None


class CreateSessionRequest(BaseModel):
    model: str | None = None     # p6.2c/p6.5：会话默认模型


class RewindRequest(BaseModel):
    keep: int  # 保留的消息条数（被编辑的用户消息下标；该条及其后全部删除）


_EFFORTS = {"low", "medium", "high", "max"}


def _known_model_ids() -> set[str]:
    from ..core.model_registry import get_dialogue_models

    return {m["id"] for m in get_dialogue_models()}


def _current_user(authorization: str | None) -> dict[str, Any]:
    """p6.2c：从 Bearer token 解析身份；fail-closed 401。"""
    from ..core.identity import resolve_user

    user = resolve_user(authorization)
    if user is None:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "未登录或登录态无效"})
    return user


_OUT_FILE = re.compile(r"^[wg]-[0-9a-f]{16}\.(md|docx|svg)$")


def _generated_file(raw: str, username: str):
    """生成文档只允许 _out/w-<16位hex>.md|docx，不按上传文件那样拍成 basename。"""
    from pathlib import Path as _P

    text = str(raw or "").replace("\\", "/").strip().lstrip("/")
    prefix = f"{username}/"
    if text.startswith(prefix):
        text = text[len(prefix):]
    parts = [part for part in text.split("/") if part and part != "."]
    if len(parts) != 2 or parts[0] != "_out" or not _OUT_FILE.match(parts[1]):
        return None
    base = _P(settings.documents_dir).resolve()
    own = (base / username).resolve()
    target = (own / "_out" / parts[1]).resolve()
    if not target.is_relative_to(own):
        raise HTTPException(400, detail={"code": "BAD_ATTACHMENT", "message": "非法附件路径"})
    if not target.is_file():
        raise HTTPException(
            400, detail={"code": "BAD_ATTACHMENT", "message": f"附件不存在：{parts[1]}"}
        )
    return target


def _validate_attachments(paths: list[str] | None, username: str) -> list[str]:
    """p6.12：校验随消息附件（fail-closed）——只允许引用**自己目录内**且真实存在的文件。

    basename 拍平（`../`、绝对路径全部拒绝）→ 限定 data/upload/<username>/ 内 → 必须存在。
    返回规范化路径列表（"<username>/<basename>"）。
    """
    if not paths:
        return []
    from pathlib import Path as _P

    base = _P(settings.documents_dir).resolve()
    own = (base / username).resolve()
    out: list[str] = []
    for raw in paths:
        name = _P(str(raw or "")).name  # 只取 basename：路径穿越/越权引用他人文件全部拍平
        if not name:
            raise HTTPException(400, detail={"code": "BAD_ATTACHMENT", "message": "附件名为空"})
        target = (own / name).resolve()
        if not target.is_relative_to(own):
            raise HTTPException(400, detail={"code": "BAD_ATTACHMENT", "message": "非法附件路径"})
        if not target.is_file():
            raise HTTPException(
                400, detail={"code": "BAD_ATTACHMENT", "message": f"附件不存在：{name}"}
            )
        out.append(f"{username}/{name}")
    return out


def _validate_attachment(path: str | None, username: str) -> list[str]:
    """单附件便捷版（返回列表，空输入返回空列表）。"""
    return _validate_attachments([path] if path else [], username)


def _compose_task_text(text: str, attachments: list[str]) -> str:
    """p6.12：附件以 prompt 前缀注入（不动正文），告知 LLM 有哪些文件可读。"""
    if not attachments:
        return text
    names = "、".join(a.split("/", 1)[-1] for a in attachments)
    return (
        f"[用户随消息上传了这些文件，已放在当前用户的上传目录：{names}。"
        f"请调用 read_document，file_name 只填文件名，不要加目录，也不要写本机路径。"
        f"回答前先读取文件内容。]\n\n{text}"
    )


@router.post("/sessions")
def create_session(body: CreateSessionRequest, authorization: str | None = Header(default=None)):
    """建会话（按登录身份）。"""
    user = _current_user(authorization)
    from ..core.session_repo import SessionRepo

    sid = SessionRepo().create_session(user["id"], body.model)
    return {"session_id": sid}


@router.get("/sessions")
def list_sessions(authorization: str | None = Header(default=None)):
    """我的会话列表（title=首条用户消息前 20 字）。"""
    user = _current_user(authorization)
    from ..core.session_repo import SessionRepo

    return {"sessions": SessionRepo().list_sessions(user["id"])}


@router.get("/sessions/{session_id}/messages")
def session_messages(session_id: str, authorization: str | None = Header(default=None)):
    """会话历史消息（归属校验：防越权读别人的会话）。"""
    user = _current_user(authorization)
    from ..core.session_repo import SessionRepo

    repo = SessionRepo()
    if not repo.session_belongs_to(session_id, user["id"]):
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    return {"messages": repo.list_messages(session_id)}


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, body: UpdateSessionRequest, authorization: str | None = Header(default=None)):
    """p6.5：更新会话默认模型（归属校验）。"""
    user = _current_user(authorization)
    if body.model is not None and body.model not in _known_model_ids():
        raise HTTPException(400, detail={"code": "BAD_MODEL", "message": f"未知模型：{body.model}"})
    from ..core.session_repo import SessionRepo

    repo = SessionRepo()
    if not repo.session_belongs_to(session_id, user["id"]):
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    fields = body.model_fields_set
    if "model" in fields:
        repo.update_session_model(session_id, body.model)
    if "title" in fields:
        repo.rename_session(session_id, (body.title or "").strip())
    if "pinned" in fields:
        repo.set_pinned(session_id, bool(body.pinned))
    return {"ok": True}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, authorization: str | None = Header(default=None)):
    user = _current_user(authorization)
    from ..core.session_repo import SessionRepo

    repo = SessionRepo()
    if not repo.session_belongs_to(session_id, user["id"]):
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    repo.delete_session(session_id)
    return {"ok": True}


@router.post("/sessions/{session_id}/rewind")
def rewind_session(session_id: str, body: RewindRequest, authorization: str | None = Header(default=None)):
    """编辑重发：删掉第 keep 条（0 起）及其后的消息，对话从这里重新开始。"""
    if body.keep < 0:
        raise HTTPException(400, detail={"code": "BAD_KEEP", "message": "keep 不能为负"})
    user = _current_user(authorization)
    from ..core.session_repo import SessionRepo

    repo = SessionRepo()
    if not repo.session_belongs_to(session_id, user["id"]):
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    deleted = repo.trim_messages_after(session_id, body.keep)
    return {"deleted": deleted}


@router.get("/quota")
def my_quota(authorization: str | None = Header(default=None)):
    """p6.4：我的 token 余额 + 最近流水（§十四 两段式结算的账本）。"""
    user = _current_user(authorization)
    from ..core.db import get_engine
    from ..core.token_pool import TokenPool

    pool = TokenPool(get_engine())
    return {
        "balance": pool.balance(user["id"]),
        "ledger": pool.recent(user["id"], limit=50),
        "usage": pool.usage_summary(user["id"]),
    }


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), authorization: str | None = Header(default=None)):
    """p6.6：上传文档到自己的目录（data/upload/<username>/），供 read_document 工具读取。

    护栏：只取 basename（防路径穿越）、格式白名单与 read_document 相同、大小上限 10MB、
    按登录用户分目录（身份隔离）。失败一律 4xx 如实说明。
    """
    from pathlib import Path as _Path

    user = _current_user(authorization)
    name = _Path(file.filename or "").name  # 只取 basename：../、绝对路径全部拍平
    if not name:
        raise HTTPException(400, detail={"code": "EMPTY_FILENAME", "message": "文件名为空"})
    from ..orchestration.tools_doc import SUPPORTED_SUFFIXES

    if not name.lower().endswith(SUPPORTED_SUFFIXES):
        allowed = "/".join(s.lstrip(".") for s in SUPPORTED_SUFFIXES)
        raise HTTPException(
            400, detail={"code": "BAD_FORMAT", "message": f"仅支持 {allowed}"}
        )
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, detail={"code": "TOO_LARGE", "message": "文件超过 10MB 上限"})
    if not content:
        raise HTTPException(400, detail={"code": "EMPTY_FILE", "message": "文件内容为空"})
    dest = _Path(settings.documents_dir) / str(user["username"]) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return {"file_name": f"{user['username']}/{name}", "size": len(content)}


@router.get("/documents/content")
def own_document(name: str, authorization: str | None = Header(default=None)):
    """预览本人已上传的文件。只读自己的目录，路径穿越按 basename 拍平后仍必须落在该目录内。"""
    from pathlib import Path as _Path

    from fastapi.responses import FileResponse, PlainTextResponse

    from ..orchestration.tools_doc import extract_document_text

    user = _current_user(authorization)
    generated = _generated_file(name, str(user["username"]))
    if generated is not None:
        path = generated
    else:
        stored = _validate_attachments([name], str(user["username"]))
        path = _Path(settings.documents_dir) / str(user["username"]) / stored[0].split("/", 1)[1]
    filename = path.name
    suffix = path.suffix.lower()
    if suffix in {".docx", ".xlsx", ".csv", ".json"}:
        try:
            body = extract_document_text(path)
        except ValueError as e:
            raise HTTPException(400, detail={"code": "EMPTY_PREVIEW", "message": str(e)}) from e
        if not body:
            raise HTTPException(400, detail={"code": "EMPTY_PREVIEW", "message": "文档内容为空"})
        return PlainTextResponse(body, media_type="text/plain; charset=utf-8")
    media = {
        ".md": "text/markdown; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".pdf": "application/pdf",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=filename, content_disposition_type="inline")


class RechargeRequest(BaseModel):
    amount: int          # 充值 token 数（>0，上限 1000 万防手滑）
    note: str | None = None


_MAX_RECHARGE = 10_000_000

#: 可续跑/重试的暂停状态（p7.1）
_RESUMABLE = {"paused_insufficient_quota", "paused_user", "paused_error", "failed"}


def _pause_reason_of(status: str) -> str | None:
    """任务状态 → 暂停原因枚举（quota/user/error/input；input 预留）。"""
    if status == "paused_insufficient_quota":
        return "quota"
    if status == "paused_user":
        return "user"
    if status in ("paused_error", "failed"):
        return "error"
    return None


def _require_admin(authorization: str | None) -> dict[str, Any]:
    """管理端守卫（fail-closed）：非 admin/superadmin 一律 403。"""
    user = _current_user(authorization)
    if str(user.get("role") or "") not in ("admin", "superadmin"):
        raise HTTPException(
            403, detail={"code": "FORBIDDEN", "message": "需要管理员权限"}
        )
    return user


@router.post("/tasks")
async def tasks_stream(body: TaskRequest, authorization: str | None = Header(default=None)):
    """跑一次编排并以 NDJSON 流式返回事件（planner→路由→Agent→done）。

    p6.2c：按登录身份落库（session + 消息 + task 记录）。
    p6.3：worker 线程 + 队列真流式（事件循环不阻塞）。
    p7.1：暂停信息落 task 行；暂停/失败不落消息（避免续跑时历史重复）。
    """
    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo

    user = _current_user(authorization)  # fail-closed：无有效身份不跑任务
    repo = SessionRepo(get_engine())
    session_id = body.session_id
    if session_id:
        if not repo.session_belongs_to(session_id, user["id"]):
            raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    else:
        session_id = repo.create_session(user["id"], body.model if hasattr(body, "model") else None)

    # p6.5：模型选择优先级 = 请求显式 > 会话默认 > 服务端默认；未知模型 400（fail-closed）
    effective_model = body.model
    if effective_model is not None and effective_model not in _known_model_ids():
        raise HTTPException(400, detail={"code": "BAD_MODEL", "message": f"未知模型：{effective_model}"})
    if effective_model is None and session_id:
        effective_model = repo.get_session_model(session_id)
    if body.effort is not None and body.effort not in _EFFORTS:
        raise HTTPException(400, detail={"code": "BAD_EFFORT", "message": f"未知力度：{body.effort}"})
    # p6.12：随消息附件——fail-closed 校验（自己目录内且存在），以 prompt 前缀注入任务文本
    validated_attachments = _validate_attachments(body.attachments, str(user["username"]))
    return _stream_task(
        user=user,
        session_id=session_id,
        text=body.text,
        attachments=validated_attachments,
        model=effective_model,
        effort=body.effort,
        estimate=body.estimate or settings.token_estimate_default,
    )


@router.post("/tasks/{task_id}/pause")
def pause_task(task_id: str, authorization: str | None = Header(default=None)):
    """用户主动暂停（p7.1）：给运行中的任务置取消标志，编排在步骤边界停下。

    运行中的任务还没有 task 行，归属靠运行登记表里的 owner_id 校验（防越权暂停）。
    """
    from ..core import runs

    user = _current_user(authorization)
    if not runs.is_running(task_id):
        raise HTTPException(
            409, detail={"code": "NOT_RUNNING", "message": "任务不在运行中（可能已完成）"}
        )
    if not runs.cancel(task_id, user["id"]):
        # 运行中但不是自己的任务：403（不泄露他人任务状态之外的信息）
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "无权暂停该任务"})
    return {"ok": True, "task_id": task_id}


@router.get("/tasks")
def my_tasks(
    status: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    authorization: str | None = Header(default=None),
):
    """我的任务列表（p7.1：刷新后还能看到"上次暂停"的横幅并继续）。"""
    import json as _json

    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo

    user = _current_user(authorization)
    rows = SessionRepo(get_engine()).list_tasks(
        user["id"], status=status, session_id=session_id, limit=limit
    )
    for row in rows:
        payload = row.get("pause_payload")
        if payload:
            try:
                row["pause_payload"] = _json.loads(payload)
            except (ValueError, TypeError):
                pass  # 存量坏数据原样返回，不因此 500
    return {"tasks": rows}


@router.get("/tasks/{task_id}")
def task_detail(task_id: str, authorization: str | None = Header(default=None)):
    import json as _json

    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo

    user = _current_user(authorization)
    repo = SessionRepo(get_engine())
    task = repo.get_task(task_id)
    if not task or not repo.task_belongs_to(task_id, user["id"]):
        raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"})
    payload = task.get("pause_payload")
    if payload:
        try:
            task["pause_payload"] = _json.loads(payload)
        except (ValueError, TypeError):
            pass
    return {"task": task}


@router.post("/tasks/{task_id}/resume")
def resume_task(task_id: str, authorization: str | None = Header(default=None)):
    """继续/重试（p7.1）：按原请求重跑，新任务 retry_of 指回原任务，返回 NDJSON 流。

    暂停原因不同、处理一致：
      · quota（余额不足）——充值后继续，零成本（原本一步没跑）；
      · user（用户主动暂停）——重跑已完成的步骤会重新计费，但跨重启可靠；
      · error（中途报错）——同 user，先排查再重试。
    真正的"断点续跑"（LangGraph 持久化 checkpoint）留作后续，见 docs。
    """
    import json as _json

    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo

    user = _current_user(authorization)
    repo = SessionRepo(get_engine())
    task = repo.get_task(task_id)
    if not task or not repo.task_belongs_to(task_id, user["id"]):
        raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"})
    status = str(task.get("status") or "")
    if status not in _RESUMABLE:
        raise HTTPException(
            409,
            detail={
                "code": "NOT_RESUMABLE",
                "message": f"当前状态（{status}）不可续跑：只有暂停或失败的任务可以继续",
            },
        )
    try:
        req = _json.loads(task.get("request_json") or "{}")
    except (ValueError, TypeError):
        req = {}
    text = str(req.get("text") or task.get("text") or "").strip()
    if not text:
        raise HTTPException(400, detail={"code": "EMPTY_TASK", "message": "原任务没有可重跑的文本"})
    attachments = _validate_attachments(req.get("attachments") or [], str(user["username"]))
    model = req.get("model") or repo.get_session_model(str(task.get("session_id") or ""))
    effort = req.get("effort")
    if effort is not None and effort not in _EFFORTS:
        effort = None
    repo.mark_task_resumed(task_id)  # 原任务标 resumed：刷新后不再反复提示旧暂停
    return _stream_task(
        user=user,
        session_id=str(task["session_id"]),
        text=text,
        attachments=attachments,
        model=model,
        effort=effort,
        estimate=settings.token_estimate_default,
        retry_of=task_id,
    )


def _stream_task(
    *,
    user: dict[str, Any],
    session_id: str,
    text: str,
    attachments: list[str],
    model: str | None,
    effort: str | None,
    estimate: int,
    retry_of: str | None = None,
) -> StreamingResponse:
    """跑一次任务并流式返回（p7.1 抽成公共实现，/tasks 与 /tasks/{id}/resume 共用）。

    落库规则：
      · done → 记 user/assistant 消息 + task 行；
      · 暂停/失败 → 只记 task 行（带 pause_reason/payload）——不写消息，避免续跑时
        历史里出现"半截对话"导致上下文重复。
    """
    import json as _json
    import logging
    import queue as _queue
    import threading

    from ..core import runs
    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo
    from ..core.token_pool import TokenPool
    from ..orchestration.graph import run_task
    from ..orchestration.memory import prepare_turn

    logger = logging.getLogger(__name__)
    repo = SessionRepo(get_engine())
    pool = TokenPool(get_engine())

    prior = repo.list_messages(session_id)
    remembered, context_parts = prepare_turn(prior, text)
    effective_text = _compose_task_text(remembered, attachments)
    if attachments:
        context_parts["current"] = effective_text

    q: _queue.Queue = _queue.Queue()
    run_id = new_run_id()
    cancel_ev = runs.register(run_id, user["id"])

    def worker() -> None:
        try:
            result, events = run_task(
                effective_text,
                user_id=user["id"],
                estimate=estimate,
                token_pool=pool,
                sink=q.put,
                model=model,
                effort=effort,
                username=str(user["username"]),
                context_parts=context_parts,
                run_id=run_id,
                cancel_event=cancel_ev,
            )
            status = str(result.get("status") or "done")
            # 落库失败不影响已完成的流（任务结果已推给用户），但必须 ERROR 级可见
            try:
                trace = _json.dumps(
                    [_json.loads(ev.model_dump_json()) for ev in events], ensure_ascii=False
                )
                if status == "done":
                    user_trace = (
                        _json.dumps({"attachments": attachments}, ensure_ascii=False)
                        if attachments
                        else None
                    )
                    repo.append_message(session_id, "user", text, trace=user_trace)
                    repo.append_message(session_id, "assistant", result.get("result", ""), trace=trace)
                payload = None
                if status == "paused_insufficient_quota":
                    ev = next((e for e in events if e.type == EventType.QUOTA_PAUSED), None)
                    payload = _json.dumps(ev.data if ev else {}, ensure_ascii=False)
                elif status == "paused_user":
                    payload = _json.dumps({"message": "用户主动暂停"}, ensure_ascii=False)
                elif status in ("paused_error", "failed"):
                    payload = _json.dumps({"error": result.get("error") or ""}, ensure_ascii=False)
                repo.record_task(
                    result.get("run_id", run_id),
                    session_id,
                    text,
                    result.get("result", ""),
                    int(result.get("tokens_used", 0)),
                    status,
                    pause_reason=_pause_reason_of(status),
                    pause_payload=payload,
                    retry_of=retry_of,
                    request_json=_json.dumps(
                        {
                            "text": text,
                            "attachments": attachments,
                            "model": model,
                            "effort": effort,
                        },
                        ensure_ascii=False,
                    ),
                )
            except Exception:  # noqa: BLE001 - 落库失败：ERROR 级记录，流照常结束
                logger.exception("会话落库失败 session_id=%s（任务结果已推给用户，但历史将缺失）", session_id)
        except Exception:  # noqa: BLE001 - worker 兜底：流以 None 收尾，异常进日志
            logger.exception("run_task worker 异常")
        finally:
            runs.finish(run_id)
            q.put(None)  # 哨兵：流结束

    threading.Thread(target=worker, daemon=True, name="run_task").start()

    def gen():
        while True:
            ev = q.get()
            if ev is None:
                break
            yield encode_line(ev)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# --------------------------------------------------------------------------- #
# 管理端（p7.1 最小版）：用户列表 + 充值 + 账本。后端按 role 强制校验（网关再挡一层）
# --------------------------------------------------------------------------- #


@router.get("/admin/users")
def admin_users(
    q: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str | None = Header(default=None),
):
    """用户列表（含余额）：用户名/工号模糊搜索。"""
    _require_admin(authorization)
    from sqlalchemy import text as _text

    from ..core.db import get_engine

    sql = (
        "SELECT u.id, u.employee_id, u.username, u.role, u.model_pool_id, "
        "COALESCE(w.balance, 0) AS balance "
        "FROM `user` u LEFT JOIN wallet w ON w.user_id = u.id"
    )
    params: dict[str, Any] = {"l": limit}
    if q and q.strip():
        sql += " WHERE u.username LIKE :kw OR u.employee_id LIKE :kw"
        params["kw"] = f"%{q.strip()}%"
    sql += " ORDER BY u.id LIMIT :l"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(_text(sql), params).mappings().all()
    return {
        "users": [
            {
                "id": int(r["id"]),
                "employee_id": r["employee_id"],
                "username": r["username"],
                "role": r["role"],
                "model_pool_id": r["model_pool_id"],
                "balance": int(r["balance"] or 0),
            }
            for r in rows
        ]
    }


@router.post("/admin/users/{user_id}/recharge")
def admin_recharge(
    user_id: int,
    body: RechargeRequest,
    authorization: str | None = Header(default=None),
):
    """充值：余额 + amount，账本记 kind=recharge（带操作人与备注）。"""
    admin = _require_admin(authorization)
    if body.amount <= 0:
        raise HTTPException(400, detail={"code": "BAD_AMOUNT", "message": "充值数量必须大于 0"})
    if body.amount > _MAX_RECHARGE:
        raise HTTPException(
            400, detail={"code": "AMOUNT_TOO_LARGE", "message": f"单次充值不能超过 {_MAX_RECHARGE}"}
        )
    from sqlalchemy import text as _text

    from ..core.db import get_engine
    from ..core.token_pool import TokenPool

    eng = get_engine()
    with eng.connect() as conn:
        exists = conn.execute(
            _text("SELECT 1 FROM `user` WHERE id = :u"), {"u": user_id}
        ).first()
    if not exists:
        raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    balance = TokenPool(eng).credit(
        user_id,
        int(body.amount),
        note=(body.note or "").strip() or None,
        operator_id=int(admin["id"]),
    )
    return {"ok": True, "user_id": user_id, "balance": balance}


@router.get("/admin/users/{user_id}/ledger")
def admin_user_ledger(
    user_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    authorization: str | None = Header(default=None),
):
    """某用户的账本流水（任务账 + 充值）。"""
    _require_admin(authorization)
    from sqlalchemy import text as _text

    from ..core.db import get_engine
    from ..core.token_pool import TokenPool

    eng = get_engine()
    with eng.connect() as conn:
        exists = conn.execute(
            _text("SELECT 1 FROM `user` WHERE id = :u"), {"u": user_id}
        ).first()
    if not exists:
        raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    return {"ledger": TokenPool(eng).recent(user_id, limit=limit)}


# --------------------------------------------------------------------------- #
# 管理端 · 概览 / 用量 / 任务（p6.26）
# --------------------------------------------------------------------------- #


def _month_start_utc() -> str:
    """本月起点（上海时区）转 UTC 字符串，与 token_ledger.usage_summary 同口径。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")


@router.get("/admin/overview")
def admin_overview(authorization: str | None = Header(default=None)):
    """管理端概览：用户/余额/任务/本月消耗/累计充值。

    口径说明：`tokens_month` 只计 kind=task 的 settle 行（真实任务消耗，不含充值）；
    `recharge_total` 只计 kind=recharge 且有 amount 的行——p6.26 之前的充值行没有
    金额字段，历史金额不臆造（如实只统计可统计部分）。
    """
    _require_admin(authorization)
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import text as _text

    from ..core.db import get_engine

    eng = get_engine()
    month_start = _month_start_utc()
    today_start = (
        datetime.now(ZoneInfo("Asia/Shanghai"))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(ZoneInfo("UTC"))
        .strftime("%Y-%m-%d %H:%M:%S")
    )
    with eng.connect() as conn:
        users_total = int(conn.execute(_text("SELECT COUNT(*) FROM `user`")).scalar() or 0)
        balance_total = int(
            conn.execute(_text("SELECT COALESCE(SUM(balance), 0) FROM wallet")).scalar() or 0
        )
        tasks_total = int(conn.execute(_text("SELECT COUNT(*) FROM task")).scalar() or 0)
        tasks_today = int(
            conn.execute(
                _text("SELECT COUNT(*) FROM task WHERE created_at >= :t"), {"t": today_start}
            ).scalar()
            or 0
        )
        tasks_paused = int(
            conn.execute(
                _text("SELECT COUNT(*) FROM task WHERE status LIKE 'paused%'")
            ).scalar()
            or 0
        )
        month_tokens, month_calls = conn.execute(
            _text(
                "SELECT COALESCE(SUM(settle), 0), COUNT(*) FROM token_ledger "
                "WHERE kind = 'task' AND settle IS NOT NULL AND created_at >= :m"
            ),
            {"m": month_start},
        ).first() or (0, 0)
        recharge_total, recharge_count = conn.execute(
            _text(
                "SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM token_ledger "
                "WHERE kind = 'recharge' AND amount IS NOT NULL"
            )
        ).first() or (0, 0)
    return {
        "users_total": users_total,
        "balance_total": balance_total,
        "tasks_total": tasks_total,
        "tasks_today": tasks_today,
        "tasks_paused": tasks_paused,
        "month_tokens": int(month_tokens or 0),
        "month_calls": int(month_calls or 0),
        "recharge_total": int(recharge_total or 0),
        "recharge_count": int(recharge_count or 0),
    }


@router.get("/admin/usage")
def admin_usage(
    days: int = Query(default=7, ge=1, le=30),
    authorization: str | None = Header(default=None),
):
    """最近 N 天任务消耗（按 settle 汇总，按天分桶）。"""
    _require_admin(authorization)
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text as _text

    from ..core.db import get_engine

    since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(
            _text(
                "SELECT DATE(created_at) AS d, COALESCE(SUM(settle), 0) AS tokens, COUNT(*) AS calls "
                "FROM token_ledger WHERE kind = 'task' AND settle IS NOT NULL AND created_at >= :s "
                "GROUP BY DATE(created_at) ORDER BY d"
            ),
            {"s": since},
        ).mappings().all()
    return {
        "days": days,
        "series": [
            {"date": str(r["d"]), "tokens": int(r["tokens"] or 0), "calls": int(r["calls"] or 0)}
            for r in rows
        ],
    }


@router.get("/admin/tasks")
def admin_tasks(
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=100),
    authorization: str | None = Header(default=None),
):
    """最近任务（全局，含所属用户/暂停原因），用于管理端任务监控。"""
    _require_admin(authorization)
    from sqlalchemy import text as _text

    from ..core.db import get_engine

    sql = (
        "SELECT t.id, t.status, t.pause_reason, t.text, t.tokens_used, t.created_at, "
        "s.user_id, u.username "
        "FROM task t LEFT JOIN session s ON s.id = t.session_id "
        "LEFT JOIN `user` u ON u.id = s.user_id"
    )
    params: dict[str, Any] = {"l": limit}
    if status:
        sql += " WHERE t.status = :st"
        params["st"] = status
    sql += " ORDER BY t.created_at DESC LIMIT :l"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(_text(sql), params).mappings().all()
    return {
        "tasks": [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "status": r["status"],
                "pause_reason": r["pause_reason"],
                "text": (r["text"] or "")[:80],
                "tokens_used": int(r["tokens_used"] or 0),
                "created_at": _iso_or_none(r["created_at"]),
            }
            for r in rows
        ]
    }


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    except Exception:  # noqa: BLE001 - 展示字段，序列化失败不阻断
        return str(value)


@router.get("/internal/auth/ping", dependencies=[Depends(require_internal)])
def internal_auth_ping():
    """内部调用自检：只有带正确 X-Internal-Token 才能进（fail-closed）。"""
    return {"ok": True, "source": "config"}


@router.get("/demo/stream")
async def demo_stream():
    """脚手架：一条 canned NDJSON 事件序列（§15.1 协议全类型演示）。

    用于验证协议/前端联调，Phase 3 真实 Agent 编排前占位；不依赖任何外部服务。
    前端 fetch + ReadableStream 按 \\n 切行逐行 JSON.parse（残行留缓冲区，§15.2）。
    """
    em = RunEventEmitter(run_id="demo-run", turn_id="demo-turn")

    def gen():
        yield em.thinking_delta("先理解需求，再决定要不要调工具……")
        yield em.tool_call_start("t1", "web_search", {"query": "办公助手"})
        yield em.observation("t1", "找到 3 条结果（此处为截断演示）", truncated=True, total=3)
        yield em.tool_call_end("t1", "web_search", success=True, duration_ms=120)
        yield em.status("planner", "running", subtask_id="sub-1")
        # p5.2：业务 Agent 身份事件（前端"当前回答 Agent"徽章的数据源）
        yield em.status("rag_retrieval", "running")
        yield em.content_delta("这是给用户的正文流。")
        yield em.artifact("a1", "excel", "http://localhost:8000/assets/a1.xlsx", "报表.xlsx")
        yield em.source("s1", "web_url", "ref-1", "参考资料", "http://example.com")
        yield em.task_summary(
            artifacts=[{"asset_id": "a1", "type": "excel", "name": "报表.xlsx"}],
            sources=[{"source_id": "s1", "type": "web_url", "title": "参考资料"}],
        )
        yield em.done("done")

    return StreamingResponse(iter_ndjson(gen()), media_type="application/x-ndjson")
