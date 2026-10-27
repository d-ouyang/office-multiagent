-- office-multiagent 初始 schema（MySQL 8）
-- 对应设计文档 §六（核心数据模型）、§十三（模型池）、§十四（token 池）
-- 仅建表 + 最小种子；业务迁移走 alembic（后续阶段）。

CREATE DATABASE IF NOT EXISTS office CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE office;

CREATE TABLE IF NOT EXISTS `user` (
  `id`              BIGINT       NOT NULL AUTO_INCREMENT,
  `employee_id`     VARCHAR(32)  NOT NULL,                 -- 身份键：工号，全局唯一永不复用（设计 §2.8），JWT sub
  `username`        VARCHAR(64)  NOT NULL,                 -- 登录键：目录内唯一、可改
  `password_hash`   VARCHAR(255) NOT NULL,
  `role`            VARCHAR(16)  NOT NULL DEFAULT 'user',  -- 管理角色：user/admin
  `model_pool_id`   BIGINT       NULL,                     -- 模型可见/池隔离（§十三）
  `token_version`   INT          NOT NULL DEFAULT 0,      -- 改密后 +1，旧 JWT 失效
  `created_at`      DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`),
  UNIQUE KEY `uk_employee_id` (`employee_id`)
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
  `title`      VARCHAR(60)  NULL,
  `pinned`     TINYINT      NOT NULL DEFAULT 0,
  `pinned_at`  DATETIME(6)  NULL,
  `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_session_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `task` (
  `id`          VARCHAR(64) NOT NULL,
  `session_id`  VARCHAR(64) NOT NULL,
  `complexity`  TINYINT     NULL,
  `status`      VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending/running/paused_insufficient_quota/paused_user/paused_error/done/failed
  `text`        MEDIUMTEXT  NULL,                        -- p6.2c：用户输入原文
  `result`      MEDIUMTEXT  NULL,                        -- p6.2c：助手终答
  `tokens_used` BIGINT      NULL,                        -- p6.2c：实际 token 用量
  `pause_reason`  VARCHAR(32) NULL,                      -- p7.1：quota/user/error/input
  `pause_payload` TEXT        NULL,                      -- p7.1：暂停上下文（余额/缺额/错误信息 JSON）
  `retry_of`      VARCHAR(64) NULL,                      -- p7.1：续跑/重试时指回原任务
  `request_json`  TEXT        NULL,                      -- p7.1：原始请求（text/attachments/model/effort）
  `created_at`  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_task_session` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `message` (
  `id`         BIGINT      NOT NULL AUTO_INCREMENT,
  `session_id` VARCHAR(64) NOT NULL,
  `role`       VARCHAR(16) NOT NULL,                    -- user/assistant
  `content`    MEDIUMTEXT  NOT NULL,
  `trace`      MEDIUMTEXT  NULL,                        -- p6.x 编排轨迹（迁移 0003；漏加会导致历史读取 500）
  `feedback`         VARCHAR(16)  NULL,                  -- v2.0.0-p2.1 当前态 like/dislike（迁移 0013）
  `feedback_tags`    LONGTEXT     NULL,                  -- 原因 tag 数组 JSON
  `feedback_comment` VARCHAR(200) NULL,                  -- 其他原因文字
  `feedback_at`      DATETIME(6)  NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_message_session` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- v2.0.0-p2.1：消息反馈流水（append-only——二次提交覆盖 message 当前态、
-- 旧行保留；取消只清当前态不删流水）。迁移 0013。
CREATE TABLE IF NOT EXISTS `message_feedback` (
  `id`         BIGINT       NOT NULL AUTO_INCREMENT,
  `message_id` BIGINT       NOT NULL,
  `session_id` VARCHAR(64)  NOT NULL,
  `user_id`    BIGINT       NOT NULL,
  `rating`     VARCHAR(16)  NOT NULL,                   -- like / dislike
  `tags`       LONGTEXT     NULL,                       -- 原因 tag 数组 JSON
  `comment`    VARCHAR(200) NULL,
  `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_feedback_message` (`message_id`),
  KEY `idx_feedback_session` (`session_id`),
  KEY `idx_feedback_user` (`user_id`)
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
  `user_id`     BIGINT      NULL,
  `type`        VARCHAR(32) NULL,   -- md/docx/bar/line 等
  `name`        VARCHAR(255) NULL,
  `rel_path`    VARCHAR(512) NULL,  -- upload/<用户>/_out/ 下的相对路径
  `storage_url` TEXT        NULL,   -- 与 rel_path 相同，预览走文档接口而不是公网 URL
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
  `kind`          VARCHAR(16) NOT NULL DEFAULT 'task',  -- p7.1：task=任务账 / recharge=充值
  `note`          VARCHAR(255) NULL,                     -- p7.1：充值备注（操作人/原因）
  `amount`        BIGINT      NULL,                      -- p6.26：充值金额（任务账为 NULL）
  `created_at`    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_ledger_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `guoquan_orders` (
  `order_no`              VARCHAR(32)  NOT NULL,
  `order_create_time`     DATETIME     NULL,
  `pay_time`               DATETIME     NULL,
  `order_status`           VARCHAR(16)  NULL,
  `order_type`             VARCHAR(16)  NULL,
  `order_channel`          VARCHAR(16)  NULL,
  `activity_id`            VARCHAR(32)  NULL,
  `activity_name`          VARCHAR(128) NULL,
  `store_id`               VARCHAR(16)  NULL,
  `store_name`             VARCHAR(64)  NULL,
  `store_address`          VARCHAR(255) NULL,
  `store_business_hours`   VARCHAR(32)  NULL,
  `store_phone`            VARCHAR(32)  NULL,
  `fulfillment_type`       VARCHAR(16)  NULL,
  `goods_list`             TEXT         NULL,
  `goods_quantity`         INT          NULL,
  `goods_amount`           DECIMAL(12,2) NULL,
  `delivery_fee`           DECIMAL(12,2) NULL,
  `packing_fee`            DECIMAL(12,2) NULL,
  `total_amount`           DECIMAL(12,2) NULL,
  `discount_amount`        DECIMAL(12,2) NULL,
  `pay_amount`             DECIMAL(12,2) NULL,
  `points_earned`          INT          NULL,
  `is_coupon_used`         VARCHAR(8)   NULL,
  `coupon_code`            VARCHAR(32)  NULL,
  `coupon_type`            VARCHAR(16)  NULL,
  `coupon_name`            VARCHAR(128) NULL,
  `coupon_value`           DECIMAL(12,2) NULL,
  `receiver_name`          VARCHAR(64)  NULL,
  `receiver_phone`         VARCHAR(20)  NULL,
  `address_id`             VARCHAR(32)  NULL,
  `address`                VARCHAR(255) NULL,
  `order_remark`           VARCHAR(255) NULL,
  `order_complete_time`    DATETIME     NULL,
  `refund_amount`          DECIMAL(12,2) NULL,
  `user_id`                VARCHAR(16)  NULL,
  `user_nickname`          VARCHAR(64)  NULL,
  `user_name`              VARCHAR(64)  NULL,
  `user_gender`            VARCHAR(8)   NULL,
  `member_level`           VARCHAR(16)  NULL,
  `member_points`          INT          NULL,
  `user_phone`             VARCHAR(20)  NULL,
  `need_invoice`           VARCHAR(8)   NULL,
  PRIMARY KEY (`order_no`),
  KEY `idx_orders_time` (`order_create_time`),
  KEY `idx_orders_store` (`store_name`),
  KEY `idx_orders_status` (`order_status`),
  KEY `idx_orders_channel` (`order_channel`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 最小种子（idempotent）=====
INSERT IGNORE INTO `model_pool` (`id`, `name`) VALUES
  (1, 'default'), (2, 'staff'), (3, 'admin');

INSERT IGNORE INTO `pool_model` (`pool_id`, `model_name`) VALUES
  (1, 'deepseek-chat'), (1, 'qwen-plus'),
  (2, 'deepseek-chat'), (2, 'qwen-plus'), (2, 'glm-4'), (2, 'deepseek-reasoner'),
  (3, 'deepseek-chat'), (3, 'qwen-plus'), (3, 'glm-4'), (3, 'kimi'), (3, 'deepseek-reasoner');

-- dev 种子：密码 Office@2026（bcrypt cost12，仅本地开发；生产改密/换 hash）
INSERT IGNORE INTO `user` (`id`, `employee_id`, `username`, `password_hash`, `role`, `model_pool_id`) VALUES
  (1, 'EMP001', 'dev', '$2b$12$bKWdpuPQGPIxCXoWyzhHaeVlvkE3eRXiiuH2Gqp6VOJDrFcVwrJrS', 'admin', 3);

-- token 池种子（p6.4）：dev 用户初始额度 100000（生产按需调整）
INSERT IGNORE INTO `wallet` (`user_id`, `balance`) VALUES (1, 100000);

-- ===== 模型池种子（p6.27c；与 backend/config/models.yaml 的 pool_ids 同名对齐）=====
-- 池身份=名字；成员以 DB pool_model 显式配置优先，无记录回落 yaml。
INSERT INTO model_pool (id, name) VALUES (1, 'default'), (2, 'staff'), (3, 'admin')
  ON DUPLICATE KEY UPDATE name = VALUES(name);

-- ===== 审计日志（p6.28a）：只写只读，无 update_time/deleted_at =====
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 审计日志（p6.28a）：只写只读，无 update_time/deleted_at =====
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 显式长期记忆（p6.29 / 迁移 0011）：用户可查可删，只增不改 =====
-- 迁移 0012：content 放宽到 TEXT，并加 section（工作背景 / 个人背景 / 当前关注 / 近期记录）
CREATE TABLE IF NOT EXISTS `user_memory` (
  `id`         BIGINT       NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT       NOT NULL,
  `section`    VARCHAR(32)  NULL,
  `content`    TEXT         NOT NULL,
  `source`     VARCHAR(16)  NOT NULL DEFAULT 'agent',
  `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_user_memory_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 运行时设置（p6.35 / 迁移 0012）：个人中心「系统」页可改的全员开关，覆盖环境变量默认值 =====
CREATE TABLE IF NOT EXISTS `runtime_setting` (
  `setting_key`   VARCHAR(64)  NOT NULL,
  `setting_value` VARCHAR(255) NOT NULL,
  `updated_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`setting_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
