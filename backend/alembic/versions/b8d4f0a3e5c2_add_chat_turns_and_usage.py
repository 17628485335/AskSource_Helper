"""add chat_turns and usage chain

Revision ID: b8d4f0a3e5c2
Revises: a7c3e9d2f4b1
Create Date: 2026-11-27 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d4f0a3e5c2'
down_revision: Union[str, None] = 'a7c3e9d2f4b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = {row[0] for row in conn.exec_driver_sql("SHOW TABLES")}

    # 新表：一轮问答的 LLM usage 汇总
    if 'chat_turns' not in tables:
        op.create_table(
            'chat_turns',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                'session_id',
                sa.Integer(),
                sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'),
                nullable=False,
                index=True,
            ),
            sa.Column('platform', sa.String(64), nullable=False, server_default=''),
            sa.Column('model', sa.String(128), nullable=False, server_default=''),
            sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_input_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_output_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('model_calls', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('input_token_details', sa.JSON(), nullable=True),
            sa.Column('output_token_details', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 存量回填：旧 turn_id 就是该轮 user 消息 id，显式用这个值建 turn 行，
    # 这样 messages / tool_calls 的 turn_id 不用改，usage 留空（老轮次无记录）。
    op.execute("""
        INSERT IGNORE INTO chat_turns (id, session_id, created_at)
        SELECT m.turn_id, m.session_id, m.created_at
        FROM chat_messages m
        WHERE m.turn_id IS NOT NULL
    """)

    # 让自增 id 从现有最大值之后开始，避免新 turn 撞到旧 id
    max_id = conn.exec_driver_sql("SELECT COALESCE(MAX(id), 0) FROM chat_turns").scalar_one()
    op.execute(f"ALTER TABLE chat_turns AUTO_INCREMENT = {int(max_id) + 1}")

    # turn_id 改为真外键：先删旧索引（FK 会自建），再加约束
    for table in ('chat_messages', 'chat_tool_calls'):
        indexes = {row[2] for row in conn.exec_driver_sql(f"SHOW INDEX FROM {table}")}
        if f'ix_{table}_turn_id' in indexes:
            op.drop_index(f'ix_{table}_turn_id', table_name=table)
        # MySQL 通过 ALTER 加 FK 时会自动建索引
        op.execute(f"""
            ALTER TABLE {table}
            ADD CONSTRAINT fk_{table}_turn_id
            FOREIGN KEY (turn_id) REFERENCES chat_turns (id) ON DELETE SET NULL
        """)


def downgrade() -> None:
    for table in ('chat_messages', 'chat_tool_calls'):
        op.execute(f"ALTER TABLE {table} DROP FOREIGN KEY fk_{table}_turn_id")
        op.create_index(f'ix_{table}_turn_id', table, ['turn_id'])
    op.drop_table('chat_turns')
