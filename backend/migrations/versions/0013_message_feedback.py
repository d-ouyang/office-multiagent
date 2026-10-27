"""消息点赞/点踩反馈（v2.0.0-p2.1）——message 当前态 + message_feedback 流水。

- `message` 加反馈四列（当前态，供消息列表快速渲染激活态）；
- `message_feedback` append-only 流水：每次提交/覆盖都插一行，旧信息天然保留
  （二次点踩覆盖当前态但历史可查）；取消只清当前态、流水不删。
- JSON 列在 MySQL 用 LONGTEXT 承载（与 task.request_json 同风格，原生 DDL 纪律）。
revision: 0013_message_feedback
down_revision: 0012_runtime_and_memory_profile
"""
from alembic import op

revision = "0013_message_feedback"
down_revision = "0012_runtime_and_memory_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE `message`
          ADD COLUMN `feedback`         VARCHAR(16)  NULL,
          ADD COLUMN `feedback_tags`    LONGTEXT     NULL,
          ADD COLUMN `feedback_comment` VARCHAR(200) NULL,
          ADD COLUMN `feedback_at`      DATETIME(6)  NULL
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS `message_feedback` (
          `id`         BIGINT       NOT NULL AUTO_INCREMENT,
          `message_id` BIGINT       NOT NULL,
          `session_id` VARCHAR(64)  NOT NULL,
          `user_id`    BIGINT       NOT NULL,
          `rating`     VARCHAR(16)  NOT NULL,
          `tags`       LONGTEXT     NULL,
          `comment`    VARCHAR(200) NULL,
          `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          KEY `idx_feedback_message` (`message_id`),
          KEY `idx_feedback_session` (`session_id`),
          KEY `idx_feedback_user` (`user_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `message_feedback`")
    op.execute(
        """
        ALTER TABLE `message`
          DROP COLUMN `feedback`,
          DROP COLUMN `feedback_tags`,
          DROP COLUMN `feedback_comment`,
          DROP COLUMN `feedback_at`
        """
    )
