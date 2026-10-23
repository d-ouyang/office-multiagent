"""任务暂停信息 + 账本充值记录（p7.1：管理端充值 / 暂停续跑）。

- task.pause_reason / pause_payload / retry_of：暂停原因（quota/user/error/input）、
  暂停上下文（余额、缺额、错误信息）、续跑时指回原任务。
- token_ledger.kind / note：task=任务账（reserve/settle），recharge=充值，
  便于 /quota 与后台按类型展示；note 记充值备注/操作人。

revision: 0008_pause_and_recharge
down_revision: 0007_session_actions
"""
from alembic import op

revision = "0008_pause_and_recharge"
down_revision = "0007_session_actions"
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
    _add_column("task", "pause_reason", "`pause_reason` VARCHAR(32) NULL")
    _add_column("task", "pause_payload", "`pause_payload` TEXT NULL")
    _add_column("task", "retry_of", "`retry_of` VARCHAR(64) NULL")
    _add_column("task", "request_json", "`request_json` TEXT NULL")
    _add_column(
        "token_ledger",
        "kind",
        # 注意：_add_column 会把 DDL 塞进单引号字符串里，内部单引号必须转义成 \'
        "`kind` VARCHAR(16) NOT NULL DEFAULT \\'task\\'",
    )
    _add_column("token_ledger", "note", "`note` VARCHAR(255) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE `token_ledger` DROP COLUMN `note`")
    op.execute("ALTER TABLE `token_ledger` DROP COLUMN `kind`")
    op.execute("ALTER TABLE `task` DROP COLUMN `request_json`")
    op.execute("ALTER TABLE `task` DROP COLUMN `retry_of`")
    op.execute("ALTER TABLE `task` DROP COLUMN `pause_payload`")
    op.execute("ALTER TABLE `task` DROP COLUMN `pause_reason`")
