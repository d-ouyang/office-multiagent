"""LLM 调用级可观测（v2.4.3）——llm_call。

背景：2.4.2 的「需要」事故靠翻日志才定位到"模型以为 group_by 只能单列"。
如果每次模型调用都落库（messages + 原始输出），同类问题 5 分钟可定位。

设计：
  · 一行 = 一次模型调用（ReAct 一步或多 Agent 一次子任务内调用）；
  · messages_json 存**实际发送**的完整 messages（手机号脱敏）；
  · 落库失败不影响任务（静默忽略）；
  · 体量大（单次几百 KB），保留 30 天由运维定期清理（不自动删，避免误删排障证据）。

revision: 0016_llm_call
down_revision: 0015_session_summary
"""
from alembic import op

revision = "0016_llm_call"
down_revision = "0015_session_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS `llm_call` (
          `id`               BIGINT       NOT NULL AUTO_INCREMENT,
          `run_id`           VARCHAR(64)  NOT NULL,
          `agent`            VARCHAR(64)  NULL,
          `step`             INT          NULL,
          `model`            VARCHAR(128) NULL,
          `messages_json`    LONGTEXT     NOT NULL,
          `response_text`    LONGTEXT     NULL,
          `prompt_tokens`    INT          NULL,
          `completion_tokens` INT         NULL,
          `ms`               INT          NULL,
          `created_at`       DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          KEY `idx_llm_call_run` (`run_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `llm_call`")
