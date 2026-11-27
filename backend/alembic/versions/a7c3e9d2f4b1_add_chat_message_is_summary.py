"""add chat_messages.is_summary and chat_summaries

Revision ID: a7c3e9d2f4b1
Revises: d4e8f2a6b0c9
Create Date: 2026-11-27 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c3e9d2f4b1'
down_revision: Union[str, None] = 'd4e8f2a6b0c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # is_summary 标记"原始消息已被摘要覆盖"，原文保留供用户翻看，但不进对话上下文
    conn = op.get_bind()
    columns = {row[0] for row in conn.exec_driver_sql("SHOW COLUMNS FROM chat_messages")}
    if 'is_summary' not in columns:
        op.add_column(
            'chat_messages',
            sa.Column('is_summary', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    indexes = {row[2] for row in conn.exec_driver_sql("SHOW INDEX FROM chat_messages")}
    if 'ix_chat_messages_is_summary' not in indexes:
        op.create_index('ix_chat_messages_is_summary', 'chat_messages', ['is_summary'])

    # 摘要内容独立成表：一个会话一条，不再混在 chat_messages 的 system 行里
    tables = {row[0] for row in conn.exec_driver_sql("SHOW TABLES")}
    if 'chat_summaries' not in tables:
        op.create_table(
            'chat_summaries',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                'session_id',
                sa.Integer(),
                sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'),
                nullable=False,
                unique=True,
                index=True,
            ),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('model', sa.String(192), nullable=False, server_default=''),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 存量迁移：把旧的 role=system 摘要行搬进新表后删除。
    # 用子查询取每个会话最新的一条 system 行作为摘要。
    op.execute("""
        INSERT INTO chat_summaries (session_id, content, model, created_at, updated_at)
        SELECT m.session_id, m.content, '', m.created_at, NOW()
        FROM chat_messages m
        JOIN (
            SELECT session_id, MAX(id) AS max_id
            FROM chat_messages
            WHERE role = 'system'
            GROUP BY session_id
        ) latest ON m.id = latest.max_id
        LEFT JOIN chat_summaries cs ON cs.session_id = m.session_id
        WHERE cs.session_id IS NULL
    """)
    op.execute("DELETE FROM chat_messages WHERE role = 'system'")


def downgrade() -> None:
    op.drop_table('chat_summaries')
    op.drop_index('ix_chat_messages_is_summary', table_name='chat_messages')
    op.drop_column('chat_messages', 'is_summary')
