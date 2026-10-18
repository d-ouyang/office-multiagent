"""内部鉴权（设计文档 §13.3，参考 RAG gateway/src/auth/internal-auth.client.ts）。

职责边界：本模块只负责【后端这一侧】——校验「网关 / 其他内部服务」带来的
`X-Internal-Token` 共享密钥。它和 NestJS 网关的 passport-jwt 用户鉴权【不冲突】：

  · 用户登录态由网关（NestJS, passport-jwt）签发 JWT，后端用 PyJWT 验同一 jwtSecret；
  · 网关↔后端之间的【内部调用】用 X-Internal-Token（共享密钥，hmac 比对），
    对应 RAG 的 internal-auth.client.ts（用 node:http 而非 fetch，避 HTTP_PROXY）；
  · 两者密钥不同、作用域不同：JWT 是「用户身份」，X-Internal-Token 是「服务间信任」。

fail-closed：secret 未配置或为空 → 一律拒绝；比对用恒定时间（防时序侧信道）。
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import APIKeyHeader

from .config import settings

logger = logging.getLogger("auth")


def verify_internal_token(token: str | None) -> bool:
    secret = settings.internal_shared_secret
    if not secret:
        logger.error("INTERNAL_SHARED_SECRET 未配置，拒绝一切内部调用（fail-closed）")
        return False
    if not token:
        return False
    return hmac.compare_digest(token, secret)


_api_key_header = APIKeyHeader(name="X-Internal-Token", auto_error=False)


def require_internal(
    x_internal_token: str | None = Depends(_api_key_header),
) -> None:
    """FastAPI 依赖：保护内部接口，缺 / 错 token 一律 401。"""
    if not verify_internal_token(x_internal_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="internal auth failed",
        )
