"""message 表 + task 记录列（p6.2c 会话持久化）。

与 0001 基线同风格：op.execute 原生 DDL 透传（与 db/init.sql 逐字一致，避开 ORM 渲染差异）。

revision: 0002_message_table
down_revision: 0001_initial
"""
from alembic import op

revision = "0002_message_table"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS `message` (
          `id`         BIGINT      NOT NULL AUTO_INCREMENT,
          `session_id` VARCHAR(64) NOT NULL,
          `role`       VARCHAR(16) NOT NULL,
          `content`    MEDIUMTEXT  NOT NULL,
          `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          KEY `idx_message_session` (`session_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    # task 记录本轮问答：用户输入 + 终答 + token 用量（幂等：information_schema 查重再加列）
    for col, ddl in (
        ("text", "MEDIUMTEXT NULL"),
        ("result", "MEDIUMTEXT NULL"),
        ("tokens_used", "BIGINT NULL"),
    ):
        exists = op.get_bind().exec_driver_sql(
            f"SELECT COUNT(*) FROM information_schema.columns "
            f"WHERE table_schema = DATABASE() AND table_name = 'task' AND column_name = '{col}'"
        ).scalar()
        if not exists:
            op.execute(f"ALTER TABLE task ADD COLUMN `{col}` {ddl}")


def downgrade() -> None:
    op.execute("ALTER TABLE task DROP COLUMN tokens_used")
    op.execute("ALTER TABLE task DROP COLUMN result")
    op.execute("ALTER TABLE task DROP COLUMN text")
    op.execute("DROP TABLE message")
