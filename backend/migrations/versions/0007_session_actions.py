"""会话可重命名、置顶。

revision: 0007_session_actions
down_revision: 0006_guoquan_orders
"""
from alembic import op

revision = "0007_session_actions"
down_revision = "0006_guoquan_orders"
branch_labels = None
depends_on = None


def _add_column(table: str, column: str, ddl: str) -> None:
    op.execute(
        f"""
        SET @exist := (
          SELECT COUNT(*) FROM information_schema.COLUMNS
          WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = '{table}'
            AND COLUMN_NAME = '{column}'
        )
        """
    )
    op.execute(
        f"""
        SET @sql := IF(
          @exist = 0,
          'ALTER TABLE `{table}` ADD COLUMN {ddl}',
          'SELECT 1'
        )
        """
    )
    op.execute("PREPARE stmt FROM @sql")
    op.execute("EXECUTE stmt")
    op.execute("DEALLOCATE PREPARE stmt")


def upgrade() -> None:
    _add_column("session", "title", "`title` VARCHAR(60) NULL")
    _add_column("session", "pinned", "`pinned` TINYINT NOT NULL DEFAULT 0")
    _add_column("session", "pinned_at", "`pinned_at` DATETIME(6) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE `session` DROP COLUMN `pinned_at`")
    op.execute("ALTER TABLE `session` DROP COLUMN `pinned`")
    op.execute("ALTER TABLE `session` DROP COLUMN `title`")
