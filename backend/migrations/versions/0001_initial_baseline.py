"""baseline：镜像 db/init.sql 的 schema + 最小种子（MySQL 8）。

Revision ID: 0001_initial
Revises: None
Create Date: 2026-10-18

幂等：CREATE TABLE IF NOT EXISTS + INSERT IGNORE，与 db/init.sql 完全一致。
compose 冷启动由 db/init.sql（docker-entrypoint-initdb.d）自建；本基线让后续
schema 演进走 alembic。test_migrations 保证本文件与 db/init.sql 不漂移。
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """v2.2.0-p1.9（C3）：原为单个多语句 op.execute——MySQL 单次 execute 不允许
    多语句，纯 alembic 全新装必炸（生产绕过：init.sql 灌库 + stamp 0001）。
    拆为逐语句后 `alembic upgrade head` 可从空库直接建全库（建库流程闭环）。
    语句与 db/init.sql 保持一致（test_migrations 护栏防漂移）；已 stamp 的生产库
    不受影响（0001 不会重跑）。"""
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `user` (
          `id`              BIGINT       NOT NULL AUTO_INCREMENT,
          `username`        VARCHAR(64)  NOT NULL,
          `password_hash`   VARCHAR(255) NOT NULL,
          `kb_role`         VARCHAR(32)  NOT NULL DEFAULT 'none',
          `model_pool_id`   BIGINT       NULL,
          `created_at`      DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_username` (`username`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `model_pool` (
          `id`   BIGINT      NOT NULL AUTO_INCREMENT,
          `name` VARCHAR(64) NOT NULL,
          PRIMARY KEY (`id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `pool_model` (
          `pool_id`    BIGINT      NOT NULL,
          `model_name` VARCHAR(128) NOT NULL,
          `enabled`    TINYINT     NOT NULL DEFAULT 1,
          PRIMARY KEY (`pool_id`, `model_name`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `session` (
          `id`         VARCHAR(64)  NOT NULL,
          `user_id`    BIGINT       NULL,
          `model`      VARCHAR(128) NULL,
          `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          KEY `idx_session_user` (`user_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `task` (
          `id`          VARCHAR(64) NOT NULL,
          `session_id`  VARCHAR(64) NOT NULL,
          `complexity`  TINYINT     NULL,
          `status`      VARCHAR(32) NOT NULL DEFAULT 'pending',
          `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          KEY `idx_task_session` (`session_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `subtask` (
          `id`          VARCHAR(64) NOT NULL,
          `task_id`     VARCHAR(64) NOT NULL,
          `agent_type`  VARCHAR(64) NULL,
          `depends_on`  JSON        NULL,
          `result_json` JSON        NULL,
          `status`      VARCHAR(32) NULL,
          PRIMARY KEY (`id`),
          KEY `idx_subtask_task` (`task_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `agent_run` (
          `id`           VARCHAR(64) NOT NULL,
          `subtask_id`   VARCHAR(64) NULL,
          `iterations`   INT         NULL,
          `token_used`   INT         NULL,
          `duration_ms`  INT         NULL,
          PRIMARY KEY (`id`),
          KEY `idx_agent_run_subtask` (`subtask_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `tool_call_log` (
          `id`           VARCHAR(64) NOT NULL,
          `agent_run_id` VARCHAR(64) NULL,
          `tool`         VARCHAR(128) NULL,
          `params`       JSON        NULL,
          `error`        TEXT        NULL,
          `success`      TINYINT     NULL,
          PRIMARY KEY (`id`),
          KEY `idx_tool_call_run` (`agent_run_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `asset` (
          `id`          VARCHAR(64) NOT NULL,
          `task_id`     VARCHAR(64) NULL,
          `type`        VARCHAR(32) NULL,
          `storage_url` TEXT        NULL,
          `created_at`  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `task_source` (
          `id`         VARCHAR(64) NOT NULL,
          `task_id`    VARCHAR(64) NULL,
          `type`       VARCHAR(32) NULL,
          `ref`        TEXT        NULL,
          `title`      VARCHAR(512) NULL,
          `url`        TEXT        NULL,
          PRIMARY KEY (`id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `wallet` (
          `user_id`  BIGINT NOT NULL,
          `balance`  BIGINT NOT NULL DEFAULT 0,
          PRIMARY KEY (`user_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `token_ledger` (
          `id`            BIGINT      NOT NULL AUTO_INCREMENT,
          `user_id`       BIGINT      NOT NULL,
          `task_id`       VARCHAR(64) NULL,
          `agent_run_id`  VARCHAR(64) NULL,
          `model`         VARCHAR(128) NULL,
          `input_tokens`  INT         NULL,
          `output_tokens` INT         NULL,
          `cache_read`    INT         NULL,
          `reserve`       INT         NULL,
          `settle`        INT         NULL,
          `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          KEY `idx_ledger_user` (`user_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    op.execute(
        """
INSERT IGNORE INTO `model_pool` (`id`, `name`) VALUES
          (1, 'default'), (2, 'staff'), (3, 'admin');
        """
    )
    op.execute(
        """
INSERT IGNORE INTO `pool_model` (`pool_id`, `model_name`) VALUES
          (1, 'deepseek-chat'), (1, 'qwen-plus'),
          (2, 'deepseek-chat'), (2, 'qwen-plus'), (2, 'glm-4'), (2, 'deepseek-reasoner'),
          (3, 'deepseek-chat'), (3, 'qwen-plus'), (3, 'glm-4'), (3, 'kimi'), (3, 'deepseek-reasoner');
        """
    )
    op.execute(
        """
INSERT IGNORE INTO `user` (`id`, `username`, `password_hash`, `kb_role`, `model_pool_id`) VALUES
          (1, 'dev', '__CHANGE_ME__', 'superadmin', 3);
        """
    )


def downgrade() -> None:
    # 本项目表间暂无物理外键，直接逆序 DROP（与建表顺序相反）
    for tbl in (
        "token_ledger",
        "wallet",
        "task_source",
        "asset",
        "tool_call_log",
        "agent_run",
        "subtask",
        "task",
        "session",
        "pool_model",
        "model_pool",
        "user",
    ):
        op.execute(f"DROP TABLE IF EXISTS `{tbl}`")
