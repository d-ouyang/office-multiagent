"""user.token_version（改密后旧 JWT 失效）。

已有库由本迁移加列；全新库的 init.sql 已带该列，这里按 information_schema 幂等，
避免两条建库路径互相踩。

revision: 0004_token_version
down_revision: 0003_message_trace
"""
from alembic import op

revision = "0004_token_version"
down_revision = "0003_message_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        SET @exist := (
          SELECT COUNT(*) FROM information_schema.COLUMNS
          WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'user'
            AND COLUMN_NAME = 'token_version'
        )
        """
    )
    op.execute(
        """
        SET @sql := IF(
          @exist = 0,
          'ALTER TABLE `user` ADD COLUMN `token_version` INT NOT NULL DEFAULT 0',
          'SELECT 1'
        )
        """
    )
    op.execute("PREPARE stmt FROM @sql")
    op.execute("EXECUTE stmt")
    op.execute("DEALLOCATE PREPARE stmt")


def downgrade() -> None:
    op.execute("ALTER TABLE `user` DROP COLUMN `token_version`")
