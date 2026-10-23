"""审计日志（p6.28a，参考 rag-qa-system 的 audit_repo 设计）。

三条结构性约束（抄设计，不抄代码）：
  1. 仓储只提供 `record` / `list_logs` / `count_logs`——**没有 update / delete**；
  2. 表里**没有** update_time / deleted_at——「顺手更新」「先软删」在 SQL 层就不成立；
  3. `record()` **拒绝**带密码 / token / 哈希特征的键与值（抛 AuditRefused，不静默丢）。

动作白名单：拼错的动作名在**写入那一刻**就抛错——否则一段时间后
`user.upd` 和 `user.update` 哪个是当初写的没人说得清，「按动作筛」事实上废掉，
而废掉的时候没有任何报错。

revision: 0010_audit_log
down_revision: 0009_ledger_amount
"""
from alembic import op

revision = "0010_audit_log"
down_revision = "0009_ledger_amount"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS `audit_log` (
          `id`             BIGINT       NOT NULL AUTO_INCREMENT,
          `actor_user_id`  BIGINT       NULL,
          `actor_username` VARCHAR(64)  NOT NULL,
          `actor_role`     VARCHAR(16)  NULL,
          `action`         VARCHAR(48)  NOT NULL,
          `target_type`    VARCHAR(24)  NOT NULL,
          `target_id`      VARCHAR(64)  NULL,
          `target_label`   VARCHAR(255) NULL,
          `detail`         TEXT         NULL,
          `ip`             VARCHAR(45)  NULL,
          `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          KEY `idx_audit_action` (`action`),
          KEY `idx_audit_actor` (`actor_user_id`),
          KEY `idx_audit_created` (`created_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `audit_log`")
