-- office-multiagent 初始 schema（MySQL 8）
-- 对应设计文档 §六（核心数据模型）、§十三（模型池）、§十四（token 池）
-- 仅建表 + 最小种子；业务迁移走 alembic（后续阶段）。

CREATE DATABASE IF NOT EXISTS office CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE office;

CREATE TABLE IF NOT EXISTS `user` (
  `id`              BIGINT       NOT NULL AUTO_INCREMENT,
  `username`        VARCHAR(64)  NOT NULL,
  `password_hash`   VARCHAR(255) NOT NULL,
  `kb_role`         VARCHAR(32)  NOT NULL DEFAULT 'none',   -- none/ops/qa/dev/superadmin（绝不塞 user.role）
  `model_pool_id`   BIGINT       NULL,
  `created_at`      DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `model_pool` (
  `id`   BIGINT      NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(64) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `pool_model` (
  `pool_id`    BIGINT      NOT NULL,
  `model_name` VARCHAR(128) NOT NULL,
  `enabled`    TINYINT     NOT NULL DEFAULT 1,
  PRIMARY KEY (`pool_id`, `model_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `session` (
  `id`         VARCHAR(64)  NOT NULL,
  `user_id`    BIGINT       NULL,
  `model`      VARCHAR(128) NULL,    -- 用户级模型选择，不跟随全局默认（§十三/§十四）
  `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_session_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `task` (
  `id`          VARCHAR(64) NOT NULL,
  `session_id`  VARCHAR(64) NOT NULL,
  `complexity`  TINYINT     NULL,
  `status`      VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending/running/paused_insufficient_quota/done/failed
  `created_at`  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_task_session` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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

CREATE TABLE IF NOT EXISTS `agent_run` (
  `id`           VARCHAR(64) NOT NULL,
  `subtask_id`   VARCHAR(64) NULL,
  `iterations`   INT         NULL,
  `token_used`   INT         NULL,
  `duration_ms`  INT         NULL,
  PRIMARY KEY (`id`),
  KEY `idx_agent_run_subtask` (`subtask_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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

CREATE TABLE IF NOT EXISTS `asset` (
  `id`          VARCHAR(64) NOT NULL,
  `task_id`     VARCHAR(64) NULL,
  `type`        VARCHAR(32) NULL,   -- image/excel/pdf/chart
  `storage_url` TEXT        NULL,
  `created_at`  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `task_source` (
  `id`         VARCHAR(64) NOT NULL,
  `task_id`    VARCHAR(64) NULL,
  `type`       VARCHAR(32) NULL,   -- rag_chunk/web_url/db_query
  `ref`        TEXT        NULL,
  `title`      VARCHAR(512) NULL,
  `url`        TEXT        NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== Token 池（§十四）=====
CREATE TABLE IF NOT EXISTS `wallet` (
  `user_id`  BIGINT NOT NULL,
  `balance`  BIGINT NOT NULL DEFAULT 0,   -- token 余额（整数）
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `token_ledger` (
  `id`            BIGINT      NOT NULL AUTO_INCREMENT,
  `user_id`       BIGINT      NOT NULL,
  `task_id`       VARCHAR(64) NULL,
  `agent_run_id`  VARCHAR(64) NULL,
  `model`         VARCHAR(128) NULL,
  `input_tokens`  INT         NULL,
  `output_tokens` INT         NULL,
  `cache_read`    INT         NULL,
  `reserve`       INT         NULL,   -- 预扣
  `settle`        INT         NULL,   -- 结算差额（可负）
  `created_at`    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_ledger_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 最小种子（idempotent）=====
INSERT IGNORE INTO `model_pool` (`id`, `name`) VALUES
  (1, 'default'), (2, 'staff'), (3, 'admin');

INSERT IGNORE INTO `pool_model` (`pool_id`, `model_name`) VALUES
  (1, 'deepseek-chat'), (1, 'qwen-plus'),
  (2, 'deepseek-chat'), (2, 'qwen-plus'), (2, 'glm-4'), (2, 'deepseek-reasoner'),
  (3, 'deepseek-chat'), (3, 'qwen-plus'), (3, 'glm-4'), (3, 'kimi'), (3, 'deepseek-reasoner');

INSERT IGNORE INTO `user` (`id`, `username`, `password_hash`, `kb_role`, `model_pool_id`) VALUES
  (1, 'dev', '__CHANGE_ME__', 'superadmin', 3);
