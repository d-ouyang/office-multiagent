"""运行时设置 + 长期记忆分区。

runtime_setting：个人中心「系统」页能改的全员开关，覆盖环境变量默认值。
user_memory.section：工作背景 / 个人背景 / 当前关注 / 近期记录。空 section 仍是短条目。

revision: 0012_runtime_and_memory_profile
down_revision: 0011_user_memory
"""
from alembic import op

revision = "0012_runtime_and_memory_profile"
down_revision = "0011_user_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS `runtime_setting` (
          `setting_key`   VARCHAR(64)  NOT NULL,
          `setting_value` VARCHAR(255) NOT NULL,
          `updated_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`setting_key`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    op.execute(
        "ALTER TABLE `user_memory` ADD COLUMN `section` VARCHAR(32) NULL"
    )
    op.execute("ALTER TABLE `user_memory` MODIFY `content` TEXT NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE `user_memory` DROP COLUMN `section`")
    op.execute("ALTER TABLE `user_memory` MODIFY `content` VARCHAR(512) NOT NULL")
    op.execute("DROP TABLE IF EXISTS `runtime_setting`")
