"""asset 补上所属用户、显示名和相对路径。

已有库由本迁移加列；全新库的 init.sql 已带这些列，按 information_schema 幂等。

revision: 0005_asset_owner
down_revision: 0004_token_version
"""
from alembic import op

revision = "0005_asset_owner"
down_revision = "0004_token_version"
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
    _add_column("asset", "user_id", "`user_id` BIGINT NULL")
    _add_column("asset", "name", "`name` VARCHAR(255) NULL")
    _add_column("asset", "rel_path", "`rel_path` VARCHAR(512) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE `asset` DROP COLUMN `rel_path`")
    op.execute("ALTER TABLE `asset` DROP COLUMN `name`")
    op.execute("ALTER TABLE `asset` DROP COLUMN `user_id`")
