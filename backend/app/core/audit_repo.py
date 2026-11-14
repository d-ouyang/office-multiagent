"""审计日志仓储（p6.28a）——只有写入与查询，没有修改与删除。

设计照搬 rag-qa-system 的三条结构性约束（代码不照搬）：
  1. 本模块不提供 update / delete（也没有「按条件改」的通用函数）；
  2. 表里没有 update_time / deleted_at，「顺手更新」「先软删」在 SQL 层不成立；
  3. `record()` 拒绝带密码 / token / 哈希特征的键与值——抛 `AuditRefused`
     而不是静默丢弃：写日志的人正是最有权限的管理员，「顺手把新密码记一下」
     这种好意一旦发生，审计表就成了密码明文的第二个落点，而它的读取权限
     往往比 user 表更宽。宁可写入失败（当场发现），也不要静默写进去。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Final

from sqlalchemy import text

from .db import get_engine

logger = logging.getLogger(__name__)

__all__ = [
    "record",
    "list_logs",
    "count_logs",
    "ACTION_LABELS",
    "TARGET_TYPES",
    "AuditRefused",
]


class AuditRefused(ValueError):
    """detail 里带了不该进审计的敏感内容。不静默丢弃，让调用方当场发现。"""


# --------------------------------------------------------------------------- #
# 动作白名单（拼错即抛错，保住「按动作筛」这个能力）
# --------------------------------------------------------------------------- #
ACTION_LABELS: Final[dict[str, str]] = {
    # 登录态（管理端独立登录）
    "admin.login.success": "管理端登录成功",
    "admin.login.failure": "管理端登录失败",
    "admin.logout": "退出管理端",
    "admin.password.change": "管理员改密",
    # 用户与额度
    "admin.recharge": "给用户充值",
    "admin.user.pool.change": "分配用户模型池",
    # v2.2.0-p1.8（C2）：死信——编排异常未被暂停/完成语义接住时登记，管理端可查
    "run.dead_letter": "任务异常死信",
    # 模型池
    "admin.pool.create": "新建模型池",
    "admin.pool.delete": "删除模型池",
    "admin.pool.models.set": "设置池模型成员",
    "admin.model.update": "更新模型登记",
    "admin.model.create": "新建模型登记",
    # 任务
    "admin.task.resume": "代续跑用户任务",
}

TARGET_TYPES: Final[tuple[str, ...]] = ("auth", "user", "task", "pool", "model", "admin")

_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "password_hash",
        "old_password",
        "new_password",
        "temp_password",
        "temporary_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "secret",
        "credential",
        "credentials",
    }
)
_FORBIDDEN_VALUE_MARKERS: Final[tuple[str, ...]] = ("$2a$", "$2b$", "$2y$")


def _walk_keys(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _walk_keys(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk_keys(item)


def _walk_strings(node: Any) -> Iterable[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk_strings(item)


def assert_detail_is_safe(detail: Any) -> None:
    """detail 不该出现密码 / token / 哈希；命中抛 AuditRefused。"""
    if detail is None:
        return
    for key in _walk_keys(detail):
        if key.lower() in _FORBIDDEN_KEYS:
            raise AuditRefused(f"审计 detail 不允许出现键「{key}」（密码 / token 类内容不进审计）")
    for value in _walk_strings(detail):
        for marker in _FORBIDDEN_VALUE_MARKERS:
            if marker in value:
                raise AuditRefused(f"审计 detail 里出现了哈希特征串（{marker}…）")


def record(
    *,
    actor_user_id: int | None,
    actor_username: str,
    actor_role: str | None,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    target_label: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> int:
    """落一条审计，返回自增 id。全关键字参数：缺一个这行日志的价值就打折。"""
    if action not in ACTION_LABELS:
        raise AuditRefused(f"未登记的动作「{action}」；先在 audit_repo.ACTION_LABELS 里加")
    assert_detail_is_safe(detail)
    payload = json.dumps(detail, ensure_ascii=False) if detail else None
    with get_engine().begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO audit_log (actor_user_id, actor_username, actor_role, action, "
                "target_type, target_id, target_label, detail, ip) "
                "VALUES (:uid, :un, :role, :act, :tt, :tid, :tl, :d, :ip)"
            ),
            {
                "uid": actor_user_id,
                "un": actor_username[:64],
                "role": (actor_role or "")[:16] or None,
                "act": action,
                "tt": target_type,
                "tid": None if target_id is None else str(target_id)[:64],
                "tl": (target_label or "")[:255] or None,
                "d": payload,
                "ip": (ip or "")[:45] or None,
            },
        )
        return int(result.lastrowid or 0)


def list_logs(
    *,
    action: str | None = None,
    target_type: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """按条件查审计（返回当页 + 筛选后总数，口径与列表分页一致）。"""
    sql = (
        "SELECT id, actor_user_id, actor_username, actor_role, action, target_type, "
        "target_id, target_label, detail, ip, created_at FROM audit_log"
    )
    params: dict[str, Any] = {"l": int(limit), "o": int(offset)}
    where: list[str] = []
    if action:
        where.append("action = :act")
        params["act"] = action
    if target_type:
        where.append("target_type = :tt")
        params["tt"] = target_type
    if keyword and keyword.strip():
        where.append(
            "(actor_username LIKE :kw OR target_label LIKE :kw OR target_id LIKE :kw OR detail LIKE :kw)"
        )
        params["kw"] = f"%{keyword.strip()}%"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT :l OFFSET :o"
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total = int(
            conn.execute(
                text("SELECT COUNT(*) FROM audit_log" + (" WHERE " + " AND ".join(where) if where else "")),
                {k: v for k, v in params.items() if k not in ("l", "o")},
            ).scalar()
            or 0
        )
    out = []
    for r in rows:
        item = dict(r)
        detail_raw = item.pop("detail", None)
        item["detail"] = None
        if detail_raw:
            try:
                item["detail"] = json.loads(detail_raw)
            except (ValueError, TypeError):
                item["detail"] = {"_raw": detail_raw}
        item["action_label"] = ACTION_LABELS.get(item["action"], item["action"])
        out.append(item)
    return out, total


def count_logs() -> int:
    with get_engine().connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM audit_log")).scalar() or 0)


def record_safe(**kwargs: Any) -> None:
    """审计写入的容错包装：失败只记日志，绝不影响主流程（充值不能因为审计挂了而失败）。"""
    try:
        record(**kwargs)
    except AuditRefused:
        # 敏感内容被拒：这是开发期问题，必须 ERROR 级可见
        logger.exception("审计 detail 含敏感内容被拒 action=%s", kwargs.get("action"))
    except Exception:  # noqa: BLE001 - 审计不可用不阻断业务
        logger.exception("审计写入失败 action=%s", kwargs.get("action"))
