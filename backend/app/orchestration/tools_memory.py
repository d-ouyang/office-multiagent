"""显式长期记忆工具（p6.29）——remember / recall。

设计纪律：
  · **显式**：只在用户明确要求记住时才调 remember；用户没让记就不调用
    （写进工具描述，靠提示词约束，不是硬护栏——误写用户随时可删）。
  · recall 关键词命中为空 ≠ 记忆为空，如实区分，防止 LLM 拿"没搜到"当"没有"。
  · 异常如实抛（ToolRegistry 会兜成错误观察），不编"已记住"。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core.config import settings
from ..core.user_memory_repo import ContentTooLong, MemoryFull, UserMemoryRepo


def make_remember_tool(repo: UserMemoryRepo, user_id: int) -> Callable[..., dict[str, Any]]:
    def remember(content: str) -> dict[str, Any]:
        try:
            row = repo.add(user_id, content, source="agent")
        except MemoryFull as e:
            raise ValueError(str(e)) from e
        except ContentTooLong as e:
            raise ValueError(str(e)) from e
        verb = "已在长期记忆中（内容相同，未重复写入）" if row.get("duplicated") else "已写入长期记忆"
        return {"saved": True, "memory_id": row["id"], "message": verb, "content": row["content"]}

    return remember


def make_recall_tool(repo: UserMemoryRepo, user_id: int) -> Callable[..., dict[str, Any]]:
    def recall(keyword: str = "") -> dict[str, Any]:
        total = repo.count(user_id)
        rows = repo.list_for(user_id, limit=settings.user_memory_inject_limit, keyword=keyword or "")
        return {
            "total": total,
            "count": len(rows),
            "keyword": keyword or None,
            "memories": [{"id": r["id"], "content": r["content"]} for r in rows],
            "note": (
                None if rows else (
                    f"该关键词没有命中任何记忆（用户共有 {total} 条记忆）。"
                    if total
                    else "该用户还没有任何长期记忆。"
                )
            ),
        }

    return recall


def register_memory_tools(registry: Any, repo: UserMemoryRepo, user_id: int) -> None:
    """往工具池挂 remember/recall（user_id 缺失=匿名场景，不挂）。"""
    registry.register(
        "remember",
        make_remember_tool(repo, user_id),
        description=(
            "把用户明确要求长期记住的信息写入该用户的记忆（偏好、常用口径、固定称呼等）。"
            "参数 content：一句话事实，最多 "
            f"{settings.user_memory_content_chars} 字。"
            "【只有用户明确要求记住时才调用】；用户没让记就不要用。"
            "临时数据、本次任务的中间结果不属于长期记忆。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "一句话事实，最多 " + f"{settings.user_memory_content_chars} 字"}
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    )
    registry.register(
        "recall",
        make_recall_tool(repo, user_id),
        description=(
            "查询当前用户的长期记忆列表。参数 keyword：可选关键词过滤；不传返回最近的记忆。"
            "用户提到「我之前说过 / 上次 / 记得吗」时用它核对，不要凭对话历史瞎猜。"
        ),
        parameters={
            "type": "object",
            "properties": {"keyword": {"type": "string", "description": "可选关键词过滤"}},
            "additionalProperties": False,
        },
    )
