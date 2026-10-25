"""API 路由：/health 联动探测、/models 模型注册表、/plan 规划路由、/internal/auth/ping 内部鉴权自检、/demo/stream NDJSON 示例。"""
import re

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
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
def models(
    pool: list[str] | None = Query(default=None, description="按模型池过滤"),
    authorization: str | None = Header(default=None),
):
    """对话下拉可见模型（§十七.1 字段）。

    p6.27c：不显式传 pool 时，按**登录用户**的 model_pool_id 过滤（§十三 池隔离落地）。
    池成员判定：DB `pool_model` 有显式配置 → 以 DB 为准；没有 → 回落 models.yaml 的
    pool_ids（新模型加进 yaml 即默认可见，不必先建 DB 行）。
    """
    items = get_dialogue_models(pool)
    if not pool:
        from ..core.db import get_engine
        from ..core.identity import resolve_user
        from sqlalchemy import text as _text

        user = resolve_user(authorization)
        pool_id = (user or {}).get("model_pool_id")
        if pool_id:
            eng = get_engine()
            with eng.connect() as conn:
                row = conn.execute(
                    _text("SELECT name FROM model_pool WHERE id = :p"), {"p": pool_id}
                ).first()
                # 注意取全部行（含 enabled=0）：只要有行就是"DB 托管"，
                # 有效池 = 其中 enabled=1 的池名（可能为空集=哪个池都看不到）
                db_rows = conn.execute(
                    _text(
                        "SELECT pm.model_name AS mn, mp.name AS pn, pm.enabled AS en "
                        "FROM pool_model pm JOIN model_pool mp ON mp.id = pm.pool_id"
                    )
                ).all()
            pool_name = str(row[0]) if row else None
            overrides: dict[str, set[str]] = {}
            for r in db_rows:
                overrides.setdefault(str(r[0]), set())
                if int(r[2] or 0) == 1:
                    overrides[str(r[0])].add(str(r[1]))
            if pool_name:
                kept = []
                for m in items:
                    pools = (
                        overrides.get(m["id"])
                        if m["id"] in overrides
                        else set(m.get("pool_ids") or [])
                    )
                    if pool_name in pools:
                        kept.append(m)
                items = kept
    return {"models": items}


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


_OUT_FILE = re.compile(r"^[weg]-[0-9a-f]{16}\.(md|docx|pdf|pptx|svg|png|csv|xlsx)$")


def _generated_file(raw: str, username: str):
    """生成产物只认 _out/ 下受控前缀、固定 id 与白名单后缀，不接受任意 basename。"""
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


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _is_image_attachment(path: str) -> bool:
    from pathlib import Path as _P

    return _P(path).suffix.lower() in _IMAGE_SUFFIXES


def _recognize_images(attachments: list[str]) -> str:
    """图片在进对话模型之前转成文字。对话模型始终只收文本。"""
    from pathlib import Path as _P

    from ..orchestration.tools_ocr import recognize_path

    base = _P(settings.documents_dir).resolve()
    blocks: list[str] = []
    for rel in attachments:
        if not _is_image_attachment(rel):
            continue
        name = rel.split("/", 1)[-1]
        try:
            text = recognize_path((base / rel).resolve())
            blocks.append(f"—— {name} ——\n{text}")
        except Exception as e:  # noqa: BLE001 - 识别失败写进提示，让模型如实告诉用户
            blocks.append(f"—— {name} ——\n识别失败：{e}")
    return "\n\n".join(blocks)


def _compose_task_text(text: str, attachments: list[str], image_text: str = "") -> str:
    """附件以 prompt 前缀注入。文档仍让模型去读；图片已经识别成文字，不再交给视觉。"""
    docs = [a for a in attachments if not _is_image_attachment(a)]
    images = [a for a in attachments if _is_image_attachment(a)]
    blocks: list[str] = []
    if docs:
        names = "、".join(a.split("/", 1)[-1] for a in docs)
        blocks.append(
            f"[用户随消息上传了这些文件，已放在当前用户的上传目录：{names}。"
            f"请调用 read_document，file_name 只填文件名，不要加目录，也不要写本机路径。"
            f"回答前先读取文件内容。]"
        )
    if images:
        names = "、".join(a.split("/", 1)[-1] for a in images)
        recognized = image_text.strip() or "（没有识别出文字）"
        blocks.append(
            f"[用户上传了图片：{names}。系统已用 DeepSeek-OCR 转成下面的文字，"
            f"对话模型看不到画面。只根据识别文字回答，不要说你看见了图片。]\n{recognized}"
        )
    if not blocks:
        return text
    return "\n\n".join(blocks) + f"\n\n{text}"


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


@router.get("/quota/usage")
def my_usage(
    model: str = Query(default="", max_length=64),
    start: str = Query(default="", max_length=10),
    end: str = Query(default="", max_length=10),
    min_tokens: int | None = Query(default=None, ge=0),
    max_tokens: int | None = Query(default=None, ge=0),
    authorization: str | None = Header(default=None),
):
    """用量明细：按模型、时间、用量筛选已结算任务，并带回会话和提问。"""
    from datetime import datetime

    user = _current_user(authorization)
    for label, raw in (("开始日期", start), ("结束日期", end)):
        if raw:
            try:
                datetime.strptime(raw, "%Y-%m-%d")
            except ValueError as e:
                raise HTTPException(400, detail={"code": "BAD_DATE", "message": f"{label}要用 YYYY-MM-DD"}) from e
    from ..core.db import get_engine
    from ..core.token_pool import TokenPool

    rows = TokenPool(get_engine()).search_usage(
        user["id"],
        model=model.strip(),
        start=start.strip(),
        end=end.strip(),
        min_tokens=min_tokens,
        max_tokens=max_tokens,
    )
    return {"items": rows}


class SettingUpdate(BaseModel):
    value: Any


@router.get("/settings")
def read_settings(authorization: str | None = Header(default=None)):
    """系统级开关。员工能看，只有管理员能改。个人模型与力度不在这里。"""
    from ..core.runtime_settings import public_items

    user = _current_user(authorization)
    return {
        "editable": str(user.get("role") or "") in ("admin", "superadmin"),
        "items": public_items(),
    }


@router.patch("/settings/{key}")
def update_setting(key: str, body: SettingUpdate, authorization: str | None = Header(default=None)):
    from ..core.runtime_settings import validate_and_store

    _require_admin(authorization)
    try:
        saved = validate_and_store(key, body.value)
    except KeyError as e:
        raise HTTPException(404, detail={"code": "UNKNOWN_SETTING", "message": "没有这项设置"}) from e
    except ValueError as e:
        raise HTTPException(400, detail={"code": "BAD_VALUE", "message": str(e)}) from e
    return {"key": key, "value": saved}


# --------------------------------------------------------------------------- #
# 显式长期记忆（p6.29）：用户可查可删；只增不改
# --------------------------------------------------------------------------- #
class MemoryCreate(BaseModel):
    content: str


class MemoryUpdate(BaseModel):
    content: str


class MemoryProfileBody(BaseModel):
    work: str = ""
    personal: str = ""
    focus: str = ""
    history: str = ""


@router.get("/memory")
def list_memory(
    keyword: str = Query(default="", max_length=64),
    authorization: str | None = Header(default=None),
):
    """我的长期记忆列表（新的在前）。keyword 可选过滤。"""
    from ..core.db import get_engine
    from ..core.user_memory_repo import UserMemoryRepo

    user = _current_user(authorization)
    repo = UserMemoryRepo(get_engine())
    rows = repo.list_for(user["id"], keyword=keyword)
    return {
        "memories": rows,
        "total": repo.count(user["id"]),
        "profile": repo.profile_for(user["id"]),
    }


@router.post("/memory")
def create_memory(body: MemoryCreate, authorization: str | None = Header(default=None)):
    """手动添加一条记忆（source=user）。内容为空/超长/已满如实 4xx。"""
    from ..core.db import get_engine
    from ..core.user_memory_repo import UserMemoryRepo

    user = _current_user(authorization)
    repo = UserMemoryRepo(get_engine())
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(400, detail={"code": "EMPTY_CONTENT", "message": "记忆内容不能为空"})
    if len(content) > settings.user_memory_content_chars:
        raise HTTPException(
            400,
            detail={
                "code": "CONTENT_TOO_LONG",
                "message": f"最多 {settings.user_memory_content_chars} 字（当前 {len(content)} 字）",
            },
        )
    from ..core.user_memory_repo import MemoryFull

    try:
        row = repo.add(user["id"], content, source="user")
    except MemoryFull as e:
        raise HTTPException(409, detail={"code": "MEMORY_FULL", "message": str(e)}) from e
    return row


@router.patch("/memory/{memory_id}")
def update_memory(memory_id: int, body: MemoryUpdate, authorization: str | None = Header(default=None)):
    """修改自己的一条短记忆。背景分区不走这里。"""
    from ..core.db import get_engine
    from ..core.user_memory_repo import ContentTooLong, UserMemoryRepo

    user = _current_user(authorization)
    try:
        row = UserMemoryRepo(get_engine()).update_fact(user["id"], memory_id, body.content or "")
    except ContentTooLong as e:
        raise HTTPException(400, detail={"code": "CONTENT_TOO_LONG", "message": str(e)}) from e
    except ValueError as e:
        raise HTTPException(400, detail={"code": "EMPTY_CONTENT", "message": str(e)}) from e
    if row is None:
        raise HTTPException(404, detail={"code": "MEMORY_NOT_FOUND", "message": "记忆不存在"})
    return row


@router.put("/memory/profile")
def save_memory_profile(body: MemoryProfileBody, authorization: str | None = Header(default=None)):
    """保存四段背景。某一段留空就是清掉这一段。"""
    from ..core.db import get_engine
    from ..core.user_memory_repo import PROFILE_SECTIONS, ContentTooLong, UserMemoryRepo

    user = _current_user(authorization)
    repo = UserMemoryRepo(get_engine())
    payload = body.model_dump()
    try:
        for key in PROFILE_SECTIONS:
            repo.save_profile(user["id"], key, payload.get(key) or "")
    except ContentTooLong as e:
        raise HTTPException(400, detail={"code": "CONTENT_TOO_LONG", "message": str(e)}) from e
    return {"profile": repo.profile_for(user["id"])}


@router.delete("/memory/{memory_id}")
def delete_memory(memory_id: int, authorization: str | None = Header(default=None)):
    """删除自己的记忆。别人的（或不存在）一律 404——不泄露存在性。"""
    from ..core.db import get_engine
    from ..core.user_memory_repo import UserMemoryRepo

    user = _current_user(authorization)
    ok = UserMemoryRepo(get_engine()).delete(user["id"], memory_id)
    if not ok:
        raise HTTPException(404, detail={"code": "MEMORY_NOT_FOUND", "message": "记忆不存在"})
    return {"deleted": True}


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
    from ..orchestration.tools_doc import IMAGE_SUFFIXES

    if name.lower().endswith(tuple(IMAGE_SUFFIXES)) and len(content) > 4 * 1024 * 1024:
        raise HTTPException(400, detail={"code": "TOO_LARGE", "message": "图片超过 4MB，请先裁小再上传"})
    if not content:
        raise HTTPException(400, detail={"code": "EMPTY_FILE", "message": "文件内容为空"})
    dest = _Path(settings.documents_dir) / str(user["username"]) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return {"file_name": f"{user['username']}/{name}", "size": len(content)}


@router.get("/documents/content")
def own_document(name: str, download: bool = Query(default=False), authorization: str | None = Header(default=None)):
    """预览/下载本人的文件。只读自己的目录，路径穿越按 basename 拍平后仍必须落在该目录内。

    p6.31：download=true 时返回原始文件（浏览器直接下载，不做任何文本抽取）——
    csv/xlsx 此前只会返回抽取文本，用户拿到手的"下载"其实是截断版。
    """
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
    if download:
        media = {
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".csv": "text/csv; charset=utf-8",
            ".pdf": "application/pdf",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(
            path, media_type=media, filename=filename, content_disposition_type="attachment"
        )
    suffix = path.suffix.lower()
    if suffix in {".docx", ".xlsx", ".csv", ".json", ".pptx"}:
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


@router.get("/documents/table")
def own_document_table(
    name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    sheet: str = Query(default="", max_length=64),
    authorization: str | None = Header(default=None),
):
    """表格文件的分页预览（p6.31）：csv / xlsx。大文件只回当前页，不再整体截成 20 行。

    返回 {columns, rows, total, offset, limit, sheets, sheet}——total 是数据行总数，
    前端据此显示"共 N 行、已加载 M 行"并按滚动增量加载。
    """
    from pathlib import Path as _Path

    from ..orchestration.tools_doc import load_table_grid

    user = _current_user(authorization)
    generated = _generated_file(name, str(user["username"]))
    if generated is not None:
        path = generated
    else:
        stored = _validate_attachments([name], str(user["username"]))
        path = _Path(settings.documents_dir) / str(user["username"]) / stored[0].split("/", 1)[1]
    if path.suffix.lower() not in (".csv", ".xlsx"):
        raise HTTPException(400, detail={"code": "NOT_A_TABLE", "message": "分页预览只支持表格文件（csv/xlsx）"})
    try:
        columns, data, sheet_name = load_table_grid(path, sheet=sheet or None)
        sheets = list(_sheet_names(path))
    except ValueError as e:
        raise HTTPException(400, detail={"code": "BAD_TABLE", "message": str(e)}) from e
    total = len(data)
    rows = data[offset : offset + limit]
    return {
        "columns": columns,
        "rows": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "sheets": sheets,
        "sheet": sheet_name,
    }


def _sheet_names(path: Any) -> list[str]:
    if path.suffix.lower() != ".xlsx":
        return []
    try:
        from openpyxl import load_workbook

        book = load_workbook(path, read_only=True)
        try:
            return list(book.sheetnames)
        finally:
            book.close()
    except Exception:  # noqa: BLE001 - 列工作表名失败不阻断预览
        return []


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


def _resume_task_impl(task_id: str, *, operator_id: int | None = None) -> StreamingResponse:
    """续跑公共实现（p7.1 自助 / p6.27b 代续跑）：按原请求重跑，新任务 retry_of 指回原任务。

    身份与归属校验由调用方负责（用户自助校验 owner；管理端代续跑只要求管理员身份）。
    代续跑以**原任务 owner** 身份计费（消耗记在任务主人头上）；operator_id 落
    request_json.operator，便于事后追溯是谁代跑的。
    """
    import json as _json

    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo

    repo = SessionRepo(get_engine())
    task = repo.get_task(task_id)
    if not task:
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
    owner_id = repo.task_owner_id(task_id)
    owner_name = repo.username_of(owner_id)
    attachments = _validate_attachments(req.get("attachments") or [], owner_name)
    model = req.get("model") or repo.get_session_model(str(task.get("session_id") or ""))
    effort = req.get("effort")
    if effort is not None and effort not in _EFFORTS:
        effort = None
    repo.mark_task_resumed(task_id)  # 原任务标 resumed：刷新后不再反复提示旧暂停
    if operator_id is not None:
        from ..core import audit_repo

        audit_repo.record_safe(
            actor_user_id=int(operator_id),
            actor_username=repo.username_of(int(operator_id)),
            actor_role="admin",
            action="admin.task.resume",
            target_type="task",
            target_id=task_id,
            detail={
                "owner_id": owner_id,
                "owner_username": owner_name,
                "text": text[:80],
            },
        )
    return _stream_task(
        user={"id": owner_id, "username": owner_name},
        session_id=str(task["session_id"]),
        text=text,
        attachments=attachments,
        model=model,
        effort=effort,
        estimate=settings.token_estimate_default,
        retry_of=task_id,
        operator_id=operator_id,
    )


@router.post("/tasks/{task_id}/resume")
def resume_task(task_id: str, authorization: str | None = Header(default=None)):
    """继续/重试（p7.1）：按原请求重跑，新任务 retry_of 指回原任务，返回 NDJSON 流。

    暂停原因不同、处理一致：
      · quota（余额不足）——充值后继续，零成本（原本一步没跑）；
      · user（用户主动暂停）——重跑已完成的步骤会重新计费，但跨重启可靠；
      · error（中途报错）——同 user，先排查再重试。
    真正的"断点续跑"（LangGraph 持久化 checkpoint）留作后续，见 docs。
    """
    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo

    user = _current_user(authorization)
    repo = SessionRepo(get_engine())
    task = repo.get_task(task_id)
    if not task or not repo.task_belongs_to(task_id, user["id"]):
        raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"})
    return _resume_task_impl(task_id)


@router.post("/admin/tasks/{task_id}/resume")
def admin_resume_task(task_id: str, authorization: str | None = Header(default=None)):
    """管理端代续跑（p6.27b）：管理员替用户继续暂停/失败的任务。

    与自助续跑的区别只在不校验 owner（管理员可操作任何人的任务）；状态限制相同
    （仅 paused/failed），消耗仍记在原任务 owner 头上，操作人 id 落 request_json.operator。
    """
    from ..core.db import get_engine
    from ..core.session_repo import SessionRepo

    admin = _require_admin(authorization)
    task = SessionRepo(get_engine()).get_task(task_id)
    if not task:
        raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"})
    return _resume_task_impl(task_id, operator_id=int(admin["id"]))


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
    operator_id: int | None = None,
) -> StreamingResponse:
    """跑一次任务并流式返回（p7.1 抽成公共实现，/tasks 与 /tasks/{id}/resume 共用；
    p6.27b 管理端代续跑也走这里，operator_id 记录代操作人）。

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
    effective_text = _compose_task_text(remembered, attachments, _recognize_images(attachments))
    if attachments:
        context_parts["current"] = effective_text

    # p6.29：显式长期记忆注入——用户此前明确要求记住的信息拼进任务文本前部，
    # 同时计入 context_usage 的 memory 分栏。查库失败不阻断任务（记忆是增强，不是依赖）。
    try:
        from ..core.user_memory_repo import UserMemoryRepo
        from ..orchestration.memory import user_memory_block

        memory_repo = UserMemoryRepo(get_engine())
        mems = memory_repo.list_for(user["id"], limit=settings.user_memory_inject_limit)
        profile = memory_repo.profile_for(user["id"])
        block = user_memory_block(mems, profile=profile, max_chars=settings.user_memory_inject_chars)
        if block:
            effective_text = f"{block}\n\n{effective_text}"
            context_parts["memory"] = block[: settings.user_memory_inject_chars]
    except Exception:  # noqa: BLE001 - 记忆注入失败不阻断任务
        logging.getLogger(__name__).exception("长期记忆注入失败（忽略）")

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
                raw_text=text,  # p6.30：planner 只看本轮原文（附件引用属本轮语境，保留在 text 里）
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
                            # p6.27b：管理员代续跑时记录操作人（自助续跑为 null）
                            "operator": operator_id,
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str | None = Header(default=None),
):
    """用户列表（含余额）：用户名/工号模糊搜索 + 分页（p6.28b）。"""
    _require_admin(authorization)
    from sqlalchemy import text as _text

    from ..core.db import get_engine

    base = (
        "FROM `user` u LEFT JOIN wallet w ON w.user_id = u.id"
    )
    where = ""
    params: dict[str, Any] = {}
    if q and q.strip():
        where = " WHERE u.username LIKE :kw OR u.employee_id LIKE :kw"
        params["kw"] = f"%{q.strip()}%"
    eng = get_engine()
    with eng.connect() as conn:
        total = int(
            conn.execute(_text("SELECT COUNT(*) " + base + where), params).scalar() or 0
        )
        rows = conn.execute(
            _text(
                "SELECT u.id, u.employee_id, u.username, u.role, u.model_pool_id, "
                "COALESCE(w.balance, 0) AS balance " + base + where +
                " ORDER BY u.id LIMIT :l OFFSET :o"
            ),
            {**params, "l": page_size, "o": (page - 1) * page_size},
        ).mappings().all()
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
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
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

    from ..core import audit_repo
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
    audit_repo.record_safe(
        actor_user_id=int(admin["id"]),
        actor_username=str(admin["username"]),
        actor_role=str(admin.get("role")),
        action="admin.recharge",
        target_type="user",
        target_id=user_id,
        target_label=str(user_id),
        detail={"amount": int(body.amount), "balance_after": balance, "note": (body.note or "").strip() or None},
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str | None = Header(default=None),
):
    """最近任务（全局，含所属用户/暂停原因）+ 分页（p6.28b）。"""
    _require_admin(authorization)
    from sqlalchemy import text as _text

    from ..core.db import get_engine

    base = (
        "FROM task t LEFT JOIN session s ON s.id = t.session_id "
        "LEFT JOIN `user` u ON u.id = s.user_id"
    )
    where = ""
    params: dict[str, Any] = {}
    if status:
        where = " WHERE t.status = :st"
        params["st"] = status
    eng = get_engine()
    with eng.connect() as conn:
        total = int(
            conn.execute(_text("SELECT COUNT(*) " + base + where), params).scalar() or 0
        )
        rows = conn.execute(
            _text(
                "SELECT t.id, t.status, t.pause_reason, t.text, t.tokens_used, t.created_at, "
                "s.user_id, u.username " + base + where +
                " ORDER BY t.created_at DESC LIMIT :l OFFSET :o"
            ),
            {**params, "l": page_size, "o": (page - 1) * page_size},
        ).mappings().all()
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
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    except Exception:  # noqa: BLE001 - 展示字段，序列化失败不阻断
        return str(value)


# --------------------------------------------------------------------------- #
# 管理端 · 审计日志（p6.28a）：只读查询；写入由各管理端点埋点 + 登录路径
# --------------------------------------------------------------------------- #


@router.get("/admin/audit-logs")
def admin_audit_logs(
    action: str | None = Query(default=None, max_length=48),
    target_type: str | None = Query(default=None, max_length=24),
    keyword: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str | None = Header(default=None),
):
    """审计日志（只读）：按动作/对象/关键词筛选 + 分页；附带动作候选（白名单）。"""
    _require_admin(authorization)
    from ..core import audit_repo

    offset = (page - 1) * page_size
    rows, total = audit_repo.list_logs(
        action=action, target_type=target_type, keyword=keyword, limit=page_size, offset=offset
    )
    return {
        "logs": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "actions": [
            {"value": k, "label": v} for k, v in audit_repo.ACTION_LABELS.items()
        ],
        "target_types": list(audit_repo.TARGET_TYPES),
    }


# --------------------------------------------------------------------------- #
# 管理端 · 独立登录/登出/改密（p6.28a）
# 登录放后端而不是网关：审计表在后端；JWT 与网关同密钥同 claims（sub=employee_id/tv），
# 两端签发的 token 互通（compose 里 GATEWAY_JWT_SECRET 同时注入两端）。
# --------------------------------------------------------------------------- #


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminPasswordRequest(BaseModel):
    old_password: str
    new_password: str


def _client_ip(request: Request) -> str | None:
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    forwarded = None
    try:
        forwarded = request.headers.get("x-forwarded-for")
    except Exception:  # noqa: BLE001 - 取不到代理头无所谓
        forwarded = None
    return (str(forwarded).split(",")[0].strip() if forwarded else host) or None


@router.post("/admin/login")
def admin_login(body: AdminLoginRequest, request: Request):
    """管理端登录：账密校验 + admin 角色 + 审计（成功/失败都写——失败也是安全事件）。"""
    import bcrypt
    import jwt as pyjwt
    from sqlalchemy import text as _text

    from ..core import audit_repo
    from ..core.db import get_engine

    ip = _client_ip(request)
    uname = (body.username or "").strip()
    with get_engine().connect() as conn:
        row = conn.execute(
            _text(
                "SELECT id, employee_id, username, password_hash, role, token_version "
                "FROM `user` WHERE username = :u"
            ),
            {"u": uname},
        ).mappings().first()
    ok = False
    if row is not None:
        try:
            ok = bcrypt.checkpw(
                (body.password or "").encode("utf-8"),
                str(row["password_hash"]).encode("utf-8"),
            )
        except Exception:  # noqa: BLE001 - 哈希格式异常等：按账密错误处理
            ok = False
    is_admin = ok and str(row["role"]) in ("admin", "superadmin")
    if ok:
        audit_repo.record_safe(
            actor_user_id=int(row["id"]),
            actor_username=str(row["username"]),
            actor_role=str(row["role"]),
            action="admin.login.success" if is_admin else "admin.login.failure",
            target_type="auth",
            target_label=uname,
            detail={"role": str(row["role"]), "admin": is_admin},
            ip=ip,
        )
    else:
        audit_repo.record_safe(
            actor_user_id=int(row["id"]) if row is not None else None,
            actor_username=uname or "(empty)",
            actor_role=str(row["role"]) if row is not None else None,
            action="admin.login.failure",
            target_type="auth",
            target_label=uname or "(empty)",
            detail={"reason": "bad_credentials"},
            ip=ip,
        )
    if not ok:
        raise HTTPException(401, detail={"code": "BAD_CREDENTIALS", "message": "用户名或密码错误"})
    if not is_admin:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "该账号没有管理员权限"})
    token = pyjwt.encode(
        {
            "sub": str(row["employee_id"]),
            "username": str(row["username"]),
            "role": str(row["role"]),
            "uid": int(row["id"]),
            "tv": int(row["token_version"] or 0),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {
        "access_token": token,
        "user": {
            "employee_id": str(row["employee_id"]),
            "username": str(row["username"]),
            "role": str(row["role"]),
        },
    }


@router.post("/admin/logout")
def admin_logout(authorization: str | None = Header(default=None)):
    """管理端登出（记账用；token 无状态，真正失效靠前端清 token / 改密踢号）。"""
    user = _current_user(authorization)
    from ..core import audit_repo

    audit_repo.record_safe(
        actor_user_id=int(user["id"]),
        actor_username=str(user["username"]),
        actor_role=str(user.get("role")),
        action="admin.logout",
        target_type="auth",
        target_label=str(user["username"]),
    )
    return {"ok": True}


@router.post("/admin/password")
def admin_change_password(
    body: AdminPasswordRequest, authorization: str | None = Header(default=None)
):
    """管理端改密（p6.28a）：验旧密 → 改新密 → token_version+1（踢掉旧登录态）
    → 签发新 admin token 返回。审计只记"改了"，不记任何密码内容。"""
    import bcrypt
    import jwt as pyjwt
    from sqlalchemy import text as _text

    from ..core import audit_repo
    from ..core.db import get_engine

    user = _current_user(authorization)
    if str(user.get("role")) not in ("admin", "superadmin"):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "需要管理员权限"})
    if len(body.new_password or "") < 6:
        raise HTTPException(400, detail={"code": "WEAK_PASSWORD", "message": "新密码至少 6 位"})
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(
            _text(
                "SELECT id, employee_id, username, role, password_hash, token_version "
                "FROM `user` WHERE id = :u"
            ),
            {"u": user["id"]},
        ).mappings().first()
        if row is None:
            raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
        try:
            ok = bcrypt.checkpw(
                (body.old_password or "").encode("utf-8"),
                str(row["password_hash"]).encode("utf-8"),
            )
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            raise HTTPException(400, detail={"code": "BAD_PASSWORD", "message": "当前密码不正确"})
        new_hash = bcrypt.hashpw((body.new_password or "").encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        conn.execute(
            _text(
                "UPDATE `user` SET password_hash = :h, token_version = token_version + 1 WHERE id = :u"
            ),
            {"h": new_hash, "u": user["id"]},
        )
        fresh = conn.execute(
            _text(
                "SELECT id, employee_id, username, role, token_version FROM `user` WHERE id = :u"
            ),
            {"u": user["id"]},
        ).mappings().first()
    audit_repo.record_safe(
        actor_user_id=int(user["id"]),
        actor_username=str(user["username"]),
        actor_role=str(user.get("role")),
        action="admin.password.change",
        target_type="admin",
        target_label=str(user["username"]),
        detail={"token_version_bumped": True},
    )
    token = pyjwt.encode(
        {
            "sub": str(fresh["employee_id"]),
            "username": str(fresh["username"]),
            "role": str(fresh["role"]),
            "uid": int(fresh["id"]),
            "tv": int(fresh["token_version"] or 0),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"ok": True, "access_token": token}


# --------------------------------------------------------------------------- #
# 管理端 · 模型池（p6.27c）：池定义 / 模型归属 / 用户分配
# 身份体系：池名（default/staff/admin，与 models.yaml 的 pool_ids 对齐）；
# 成员判定：DB pool_model 显式配置优先，无记录回落 yaml。
# --------------------------------------------------------------------------- #


class CreatePoolRequest(BaseModel):
    name: str


class SetPoolModelsRequest(BaseModel):
    models: list[dict[str, Any]]  # [{model_name, enabled}]


class SetUserPoolRequest(BaseModel):
    model_pool_id: int | None = None


@router.get("/admin/model-pools")
def admin_model_pools(authorization: str | None = Header(default=None)):
    """池列表 + 每个池的模型矩阵（enabled=生效成员：DB 显式配置，否则 yaml 默认）。"""
    _require_admin(authorization)
    from sqlalchemy import text as _text

    from ..core.db import get_engine
    from ..core.model_registry import load_registry

    reg = load_registry()
    dialogue = [m.id for m in reg["models"] if m.in_dialogue]
    yaml_pools = {m.id: set(m.pool_ids) for m in reg["models"]}
    eng = get_engine()
    with eng.connect() as conn:
        pools = conn.execute(_text("SELECT id, name FROM model_pool ORDER BY id")).all()
        members = conn.execute(
            _text("SELECT pool_id, model_name, enabled FROM pool_model")
        ).all()
        user_counts = {
            int(r[0]): int(r[1])
            for r in conn.execute(
                _text("SELECT model_pool_id, COUNT(*) FROM `user` GROUP BY model_pool_id")
            ).all()
            if r[0] is not None
        }
    db: dict[int, dict[str, bool]] = {}
    for r in members:
        db.setdefault(int(r[0]), {})[str(r[1])] = bool(r[2])
    return {
        "pools": [
            {
                "id": int(p[0]),
                "name": str(p[1]),
                "user_count": user_counts.get(int(p[0]), 0),
                "models": [
                    {
                        "model_name": name,
                        # 生效成员：DB 显式配置优先；无记录回落 yaml（池名 ∈ 该模型的 pool_ids）
                        "enabled": db.get(int(p[0]), {}).get(
                            name, str(p[1]) in yaml_pools.get(name, set())
                        ),
                    }
                    for name in dialogue
                ],
            }
            for p in pools
        ]
    }


@router.post("/admin/model-pools")
def admin_create_pool(body: CreatePoolRequest, authorization: str | None = Header(default=None)):
    """新建模型池（名字唯一，如 finance / trial）。"""
    admin = _require_admin(authorization)
    name = (body.name or "").strip()
    if not name or len(name) > 32:
        raise HTTPException(400, detail={"code": "BAD_NAME", "message": "池名 1~32 字符"})
    from sqlalchemy import text as _text

    from ..core import audit_repo
    from ..core.db import get_engine

    eng = get_engine()
    with eng.begin() as conn:
        exists = conn.execute(
            _text("SELECT 1 FROM model_pool WHERE name = :n"), {"n": name}
        ).first()
        if exists:
            raise HTTPException(409, detail={"code": "POOL_EXISTS", "message": "同名池已存在"})
        conn.execute(_text("INSERT INTO model_pool (name) VALUES (:n)"), {"n": name})
        row = conn.execute(
            _text("SELECT id, name FROM model_pool WHERE name = :n"), {"n": name}
        ).first()
    audit_repo.record_safe(
        actor_user_id=int(admin["id"]), actor_username=str(admin["username"]),
        actor_role=str(admin.get("role")), action="admin.pool.create",
        target_type="pool", target_id=int(row[0]), target_label=name,
    )
    return {"ok": True, "id": int(row[0]), "name": str(row[1])}


@router.put("/admin/model-pools/{pool_id}/models")
def admin_set_pool_models(
    pool_id: int,
    body: SetPoolModelsRequest,
    authorization: str | None = Header(default=None),
):
    """全量设置某池的模型成员（enabled=true 的行入库，false 的不留）。"""
    admin = _require_admin(authorization)
    from sqlalchemy import text as _text

    from ..core import audit_repo
    from ..core.db import get_engine
    from ..core.model_registry import load_registry

    known = {m.id for m in load_registry()["models"] if m.in_dialogue}
    rows = []
    for item in body.models:
        name = str(item.get("model_name") or "")
        if name not in known:
            raise HTTPException(400, detail={"code": "BAD_MODEL", "message": f"未知对话模型：{name}"})
        if item.get("enabled"):
            rows.append(name)
    eng = get_engine()
    with eng.begin() as conn:
        pool = conn.execute(
            _text("SELECT id FROM model_pool WHERE id = :p"), {"p": pool_id}
        ).first()
        if not pool:
            raise HTTPException(404, detail={"code": "POOL_NOT_FOUND", "message": "池不存在"})
        conn.execute(_text("DELETE FROM pool_model WHERE pool_id = :p"), {"p": pool_id})
        # 全量写入（含 enabled=0）：一旦某模型在该池有行，成员权就归 DB，
        # 不会再回落 yaml——否则"显式关闭"会被误判成"没配置"而重新可见。
        for item in body.models:
            name = str(item.get("model_name") or "")
            conn.execute(
                _text(
                    "INSERT INTO pool_model (pool_id, model_name, enabled) VALUES (:p, :m, :e)"
                ),
                {"p": pool_id, "m": name, "e": 1 if item.get("enabled") else 0},
            )
    audit_repo.record_safe(
        actor_user_id=int(admin["id"]), actor_username=str(admin["username"]),
        actor_role=str(admin.get("role")), action="admin.pool.models.set",
        target_type="pool", target_id=pool_id, detail={"enabled": rows},
    )
    return {"ok": True, "pool_id": pool_id, "enabled_count": len(rows)}


@router.delete("/admin/model-pools/{pool_id}")
def admin_delete_pool(pool_id: int, authorization: str | None = Header(default=None)):
    """删除池；仍有用户在该池时拒绝（先把用户移走，避免静默失去模型可见性）。"""
    admin = _require_admin(authorization)
    from sqlalchemy import text as _text

    from ..core import audit_repo
    from ..core.db import get_engine

    eng = get_engine()
    with eng.begin() as conn:
        pool = conn.execute(
            _text("SELECT id FROM model_pool WHERE id = :p"), {"p": pool_id}
        ).first()
        if not pool:
            raise HTTPException(404, detail={"code": "POOL_NOT_FOUND", "message": "池不存在"})
        used = conn.execute(
            _text("SELECT COUNT(*) FROM `user` WHERE model_pool_id = :p"), {"p": pool_id}
        ).scalar()
        if used:
            raise HTTPException(
                409,
                detail={
                    "code": "POOL_IN_USE",
                    "message": f"还有 {int(used)} 个用户在该池，请先把他们移到别的池",
                },
            )
        conn.execute(_text("DELETE FROM pool_model WHERE pool_id = :p"), {"p": pool_id})
        conn.execute(_text("DELETE FROM model_pool WHERE id = :p"), {"p": pool_id})
    audit_repo.record_safe(
        actor_user_id=int(admin["id"]), actor_username=str(admin["username"]),
        actor_role=str(admin.get("role")), action="admin.pool.delete",
        target_type="pool", target_id=pool_id,
    )
    return {"ok": True}


@router.patch("/admin/users/{user_id}/pool")
def admin_set_user_pool(
    user_id: int,
    body: SetUserPoolRequest,
    authorization: str | None = Header(default=None),
):
    """分配用户的模型池（null=不限制，可见全部对话模型）。"""
    admin = _require_admin(authorization)
    from sqlalchemy import text as _text

    from ..core import audit_repo
    from ..core.db import get_engine

    eng = get_engine()
    with eng.begin() as conn:
        exists = conn.execute(
            _text("SELECT 1 FROM `user` WHERE id = :u"), {"u": user_id}
        ).first()
        if not exists:
            raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
        if body.model_pool_id is not None:
            pool = conn.execute(
                _text("SELECT id FROM model_pool WHERE id = :p"), {"p": body.model_pool_id}
            ).first()
            if not pool:
                raise HTTPException(404, detail={"code": "POOL_NOT_FOUND", "message": "池不存在"})
        conn.execute(
            _text("UPDATE `user` SET model_pool_id = :p WHERE id = :u"),
            {"p": body.model_pool_id, "u": user_id},
        )
    audit_repo.record_safe(
        actor_user_id=int(admin["id"]),
        actor_username=str(admin["username"]),
        actor_role=str(admin.get("role")),
        action="admin.user.pool.change",
        target_type="user",
        target_id=user_id,
        detail={"model_pool_id": body.model_pool_id},
    )
    return {"ok": True, "user_id": user_id, "model_pool_id": body.model_pool_id}


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
