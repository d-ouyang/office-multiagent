"""账本充值金额（p6.26 管理端概览：累计充值要看金额，不能只数条数）。

充值行（kind=recharge）在 `amount` 记金额；任务账（kind=task）为 NULL，
reserve/settle 语义不变。存量充值行 amount 为 NULL（当时只记了 note），
概览统计如实按"可统计的充值"计算，不臆造历史金额。

revision: 0009_ledger_amount
down_revision: 0008_pause_and_recharge
"""
from alembic import op

revision = "0009_ledger_amount"
down_revision = "0008_pause_and_recharge"
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
        SET @sql := IF(@exist = 0, 'ALTER TABLE `{table}` ADD COLUMN {ddl}', 'SELECT 1')
        """
    )
    op.execute("PREPARE stmt FROM @sql")
    op.execute("EXECUTE stmt")
    op.execute("DEALLOCATE PREPARE stmt")


def upgrade() -> None:
    _add_column("token_ledger", "amount", "`amount` BIGINT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE `token_ledger` DROP COLUMN `amount`")
