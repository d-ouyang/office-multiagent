"""会话轮次结构化摘要（v2.4.2）——session_summary。

v2.4.1 及之前，更早轮次是用 `answer[:80]` 切片当"摘要"：730 字的回答被砍成 "- 时…"，
结尾「需要我导出成文档吗」直接丢，用户回「需要」时模型无从对上。

本表存**一轮一条**的结构化摘要（意图/结论/数字/产物/未决问题）：
  · 生成后永久复用，不再重算；
  · `turn_no` 与 message 顺序对齐（第 N 个 QA 对）；
  · 只有摘要总量超预算时，才把最老的几条**合并**成一条（合并已有记录，不重读原文）。

revision: 0015_session_summary
down_revision: 0014_tool_invocation
"""
from alembic import op

revision = "0015_session_summary"
down_revision = "0014_tool_invocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS `session_summary` (
          `session_id` VARCHAR(64)  NOT NULL,
          `turn_no`    INT          NOT NULL,
          `payload`    JSON         NOT NULL,
          `rendered`   TEXT         NULL,
          `engine`     VARCHAR(16)  NOT NULL DEFAULT 'rule',
          `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (`session_id`, `turn_no`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `session_summary`")
