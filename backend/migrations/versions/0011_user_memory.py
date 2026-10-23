"""显式长期记忆（p6.29）——user_memory 表，用户可查可删。

只增不改：没有 update_time / deleted 列；删除即物理删（用户要求"忘掉"就该真的没有）。
revision: 0011_user_memory
down_revision: 0010_audit_log
"""
from alembic import op

revision = "0011_user_memory"
down_revision = "0010_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS `user_memory` (
          `id`         BIGINT       NOT NULL AUTO_INCREMENT,
          `user_id`    BIGINT       NOT NULL,
          `content`    VARCHAR(512) NOT NULL,
          `source`     VARCHAR(16)  NOT NULL DEFAULT 'agent',
          `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          KEY `idx_user_memory_user` (`user_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `user_memory`")
