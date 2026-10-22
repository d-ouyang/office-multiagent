"""API 路由：/health 联动探测、/models 模型注册表、/plan 规划路由、/internal/auth/ping 内部鉴权自检、/demo/stream NDJSON 示例。"""
import re

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from typing import Any

from ..core import chroma_client, db, redis_client
from ..core.config import settings
from ..core.events import EventType, RunEventEmitter, encode_line, iter_ndjson
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


@router.post("/tasks")
async def tasks_stream(body: TaskRequest, authorization: str | None = Header(default=None)):
    """跑一次编排并以 NDJSON 流式返回事件（planner→路由→Agent→done）。

    带 user_id 时前置 token 池 reserve（p4.2）：余额不足→quota_paused 中断；
    完成 settle。受网关 JWT 保护。

    p6.2c：按登录身份落库——session（不传则自动新建）+ 本轮 user/assistant 消息
    + task 记录（run_id/终答/用量）。
    p6.3 真流式管道：编排在 worker 线程里跑，事件经 sink 实时推 queue，
    同步 gen 从 queue 逐条 yield（Starlette 自动丢线程池消费，事件循环不阻塞）；
    LLM 的每个生成 chunk 即时变成 content_delta/thinking_delta 到前端（打字机）。
    """
    import logging
    import queue as _queue
    import threading

    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo
    from ..core.token_pool import TokenPool
    from ..orchestration.graph import run_task

    logger = logging.getLogger(__name__)
    user = _current_user(authorization)  # fail-closed：无有效身份不跑任务
    repo = SessionRepo(get_engine())
    session_id = body.session_id
    if session_id:
        if not repo.session_belongs_to(session_id, user["id"]):
            raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    else:
        session_id = repo.create_session(user["id"], body.model if hasattr(body, "model") else None)

    # p6.4：token 池真账——用户 id 取自登录身份（body.user_id 仅测试覆盖用），
    # estimate 用默认门槛值（真实用量在 settle 时补差，§十四 两段式）
    pool = TokenPool(get_engine())
    effective_user_id = body.user_id if body.user_id is not None else user["id"]
    estimate = body.estimate or settings.token_estimate_default
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
    from ..orchestration.memory import prepare_turn

    prior = repo.list_messages(session_id) if session_id else []
    remembered, context_parts = prepare_turn(prior, body.text)
    effective_text = _compose_task_text(remembered, validated_attachments)
    if validated_attachments:
        context_parts["current"] = effective_text
    q: _queue.Queue = _queue.Queue()

    def worker() -> None:
        try:
            result, events = run_task(
                effective_text,
                user_id=effective_user_id,
                estimate=estimate,
                token_pool=pool,
                sink=q.put,
                model=effective_model,
                effort=body.effort,
                username=str(user["username"]),
                context_parts=context_parts,
            )
            # p6.2c/p6.7：落库（user 消息 + assistant 终答+过程事件 trace + task 记录）。
            # 落库失败不影响已完成的流（任务结果已推给用户），但必须 ERROR 级可见
            # ——p6.7 教训：异常只进 debug 日志等于"失败不可见"。
            try:
                import json as _json

                trace = _json.dumps(
                    [_json.loads(ev.model_dump_json()) for ev in events], ensure_ascii=False
                )
                # p6.12：user 消息 trace 存附件列表（历史重建时前端渲染附件 chip）；
                # 正文仍存原始输入（不混入 prompt 前缀）。
                user_trace = (
                    _json.dumps({"attachments": validated_attachments}, ensure_ascii=False)
                    if validated_attachments
                    else None
                )
                repo.append_message(session_id, "user", body.text, trace=user_trace)
                repo.append_message(session_id, "assistant", result.get("result", ""), trace=trace)
                repo.record_task(
                    result.get("run_id", ""),
                    session_id,
                    body.text,
                    result.get("result", ""),
                    int(result.get("tokens_used", 0)),
                    str(result.get("status", "done")),
                )
            except Exception:  # noqa: BLE001 - 落库失败：ERROR 级记录，流照常结束
                logger.exception("会话落库失败 session_id=%s（任务结果已推给用户，但历史将缺失）", session_id)
        except Exception:  # noqa: BLE001 - worker 兜底：流以 None 收尾，异常进日志
            logger.exception("run_task worker 异常")
        finally:
            q.put(None)  # 哨兵：流结束

    threading.Thread(target=worker, daemon=True, name="run_task").start()

    def gen():
        while True:
            ev = q.get()
            if ev is None:
                break
            yield encode_line(ev)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


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
