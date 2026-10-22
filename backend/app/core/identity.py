"""用户身份解析（p6.2c）——从 Authorization Bearer token 解出 office 用户行。

信任链：网关验过签的 JWT，后端再验一次（双保险，§13.3）；`sub = employee_id`（§2.8）。
fail-closed：无 token / 验签失败 / secret 未配 / 查无此人 → None（调用方 401）。
"""
from __future__ import annotations

import logging
from typing import Any

import jwt as pyjwt
from sqlalchemy import text

from .config import settings
from .db import get_engine

logger = logging.getLogger(__name__)


def resolve_user(authorization: str | None) -> dict[str, Any] | None:
    """Bearer token → user 行（id/employee_id/username/role/model_pool_id）；失败返回 None。"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer "):].strip()
    if not token:
        return None
    if not settings.jwt_secret:
        logger.warning("JWT_SECRET 未配置，身份解析 fail-closed")
        return None
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except pyjwt.PyJWTError as e:
        logger.info("JWT 验签失败：%s", e)
        return None
    employee_id = str(payload.get("sub") or "")
    if not employee_id:
        return None
    tv = int(payload.get("tv") or 0)
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, employee_id, username, role, model_pool_id, token_version "
                    "FROM `user` WHERE employee_id = :eid"
                ),
                {"eid": employee_id},
            ).mappings().first()
    except Exception as e:  # noqa: BLE001 - 库不可用或列未迁移：fail-closed
        logger.warning("身份查询失败：%s", e)
        return None
    if not row:
        return None
    if int(row.get("token_version") or 0) != tv:
        logger.info("JWT token_version 不匹配，旧登录态已失效 employee_id=%s", employee_id)
        return None
    return dict(row)
