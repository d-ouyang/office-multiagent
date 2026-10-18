"""API 路由：/health 联动探测、/models 模型注册表、/internal/auth/ping 内部鉴权自检。"""
from fastapi import APIRouter, Depends, Query

from ..core import chroma_client, db, redis_client
from ..core.config import settings
from ..core.internal_auth import require_internal
from ..core.model_registry import get_dialogue_models

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


@router.get("/internal/auth/ping", dependencies=[Depends(require_internal)])
def internal_auth_ping():
    """内部调用自检：只有带正确 X-Internal-Token 才能进（fail-closed）。"""
    return {"ok": True, "source": "config"}
