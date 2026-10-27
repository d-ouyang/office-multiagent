"""消息反馈仓储（v2.0.0-p2.1）——点赞/点踩闭环的数据层。

设计（PLAN-2.0.0 §4.3）：
  · 当前态存 `message` 表四列（消息列表快速渲染激活态）；
  · 每次提交/覆盖都往 `message_feedback` 插一行流水（append-only）——
    二次点踩覆盖当前态、旧信息保留在流水；取消只清当前态、流水不删。
  · 归属校验在路由层做 404 同形，这里只管「message 是否可反馈」。

标签白名单与前端约定一致（多选）；comment ≤200。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

RATINGS = ("like", "dislike")

FEEDBACK_TAGS = (
    "误解了我的问题",
    "上下文理解错误",
    "回答模糊、不具体",
    "数据或数字有误",
    "图表或表格有误",
    "工具调用有误",
    "回答不专业",
    "其他原因",
)

COMMENT_MAX = 200


class FeedbackValidationError(ValueError):
    """业务校验失败（路由层转 400）。"""


class FeedbackRepo:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # ---- 查询 ----
    def get_message_for(self, session_id: str, message_id: int, user_id: int) -> dict[str, Any] | None:
        """取一条消息并校验：属于该会话、会话属于该用户、role=assistant。"""
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT m.id, m.session_id, m.role, m.feedback, m.feedback_tags, "
                    "m.feedback_comment, m.feedback_at "
                    "FROM message m JOIN session s ON s.id = m.session_id "
                    "WHERE m.id = :mid AND m.session_id = :sid AND s.user_id = :uid"
                ),
                {"mid": message_id, "sid": session_id, "uid": user_id},
            ).mappings().first()
        if row is None or row["role"] != "assistant":
            return None
        return dict(row)

    # ---- 写入 ----
    def submit(
        self,
        session_id: str,
        message_id: int,
        user_id: int,
        rating: str,
        tags: list[str] | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """提交/覆盖反馈：插流水 + upsert 当前态。返回最新当前态。"""
        if rating not in RATINGS:
            raise FeedbackValidationError(f"rating 只能是 {' / '.join(RATINGS)}")
        tags = [t for t in (tags or []) if t]
        bad = [t for t in tags if t not in FEEDBACK_TAGS]
        if bad:
            raise FeedbackValidationError(f"未知反馈标签：{bad}")
        comment = (comment or "").strip()
        if len(comment) > COMMENT_MAX:
            raise FeedbackValidationError(f"反馈说明最多 {COMMENT_MAX} 字")
        if rating == "dislike" and not tags and not comment:
            raise FeedbackValidationError("点踩至少选择一个原因或填写其他原因")
        if rating == "like":
            tags, comment = [], ""  # 点赞不携带原因

        tags_json = json.dumps(tags, ensure_ascii=False) if tags else None
        now = datetime.utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO message_feedback (message_id, session_id, user_id, rating, tags, comment) "
                    "VALUES (:m, :s, :u, :r, :t, :c)"
                ),
                {"m": message_id, "s": session_id, "u": user_id, "r": rating, "t": tags_json, "c": comment or None},
            )
            conn.execute(
                text(
                    "UPDATE message SET feedback = :r, feedback_tags = :t, "
                    "feedback_comment = :c, feedback_at = :now WHERE id = :m"
                ),
                {"r": rating, "t": tags_json, "c": comment or None, "m": message_id, "now": now},
            )
        return self.current_state(message_id)

    def cancel(self, session_id: str, message_id: int, user_id: int) -> bool:
        """取消反馈：清当前态；流水行保留（历史可查）。返回是否存在过当前态。"""
        state = self.get_message_for(session_id, message_id, user_id)
        if state is None:
            return False
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE message SET feedback = NULL, feedback_tags = NULL, "
                    "feedback_comment = NULL, feedback_at = NULL WHERE id = :m"
                ),
                {"m": message_id},
            )
        return state.get("feedback") is not None

    def current_state(self, message_id: int) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, feedback, feedback_tags, feedback_comment, feedback_at "
                    "FROM message WHERE id = :m"
                ),
                {"m": message_id},
            ).mappings().first()
        if row is None:
            return {"id": message_id, "feedback": None, "tags": None, "comment": None, "at": None}
        tags = row["feedback_tags"]
        at = row["feedback_at"]
        return {
            "id": row["id"],
            "feedback": row["feedback"],
            "tags": json.loads(tags) if tags else [],
            "comment": row["feedback_comment"],
            "at": at.isoformat() if hasattr(at, "isoformat") else at,
        }
