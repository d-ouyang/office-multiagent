"""幂等键贯穿（v2.2.0-p1.7 / Phase C1）——tool_invocation 去重表。

C 阶段的执行保障地基：断点续跑/重试/重投时，副作用类工具凭
UNIQUE(run_id, tool_name, args_hash) 保证只执行一次（第二次直接取缓存观察）。
revision: 0014_tool_invocation
down_revision: 0013_message_feedback
"""
from alembic import op

revision = "0014_tool_invocation"
down_revision = "0013_message_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS `tool_invocation` (
          `id`         BIGINT       NOT NULL AUTO_INCREMENT,
          `run_id`     VARCHAR(64)  NOT NULL,
          `tool_name`  VARCHAR(128) NOT NULL,
          `args_hash`  CHAR(64)     NOT NULL,
          `args_preview` VARCHAR(512) NULL,
          `observation` TEXT       NULL,
          `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          UNIQUE KEY `uq_tool_invocation` (`run_id`, `tool_name`, `args_hash`),
          KEY `idx_tool_invocation_run` (`run_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `tool_invocation`")
