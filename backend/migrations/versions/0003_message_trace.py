"""message.trace 过程事件列（p6.7 过程透明+落库）——一轮问答的完整事件流
（thinking/tool_call/observation/status/content_delta）随 assistant 消息一起落库，
刷新/切会话不丢失；前端按 trace 重建过程渲染（折叠思考/步骤 + markdown 终答）。

revision: 0003_message_trace
down_revision: 0002_message_table
"""
from alembic import op

revision = "0003_message_trace"
down_revision = "0002_message_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE message ADD COLUMN trace MEDIUMTEXT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE message DROP COLUMN trace")
