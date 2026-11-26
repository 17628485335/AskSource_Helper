"""add chat_tool_calls and chat_messages.turn_id

Revision ID: f2a7c4e9b1d3
Revises: d8f3a1c7b9e2
Create Date: 2026-11-26 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a7c4e9b1d3'
down_revision: Union[str, None] = 'd8f3a1c7b9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # turn_id 取该轮 user 消息 id；老消息保持 NULL，不回填
    op.add_column('chat_messages', sa.Column('turn_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_chat_messages_turn_id'), 'chat_messages', ['turn_id'], unique=False)

    op.create_table(
        'chat_tool_calls',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('turn_id', sa.Integer(), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('segment_id', sa.Integer(), nullable=True),
        sa.Column('tool_name', sa.String(length=128), nullable=False),
        sa.Column('call_id', sa.String(length=128), nullable=False),
        sa.Column('input_json', sa.JSON(), nullable=True),
        sa.Column('result_text', sa.Text(), nullable=False),
        sa.Column('preview', sa.Text(), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('citations_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['chat_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_chat_tool_calls_session_id'), 'chat_tool_calls', ['session_id'], unique=False)
    op.create_index(op.f('ix_chat_tool_calls_message_id'), 'chat_tool_calls', ['message_id'], unique=False)
    op.create_index(op.f('ix_chat_tool_calls_turn_id'), 'chat_tool_calls', ['turn_id'], unique=False)
    op.create_index(op.f('ix_chat_tool_calls_tool_name'), 'chat_tool_calls', ['tool_name'], unique=False)
    op.create_index(op.f('ix_chat_tool_calls_call_id'), 'chat_tool_calls', ['call_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chat_tool_calls_call_id'), table_name='chat_tool_calls')
    op.drop_index(op.f('ix_chat_tool_calls_tool_name'), table_name='chat_tool_calls')
    op.drop_index(op.f('ix_chat_tool_calls_turn_id'), table_name='chat_tool_calls')
    op.drop_index(op.f('ix_chat_tool_calls_message_id'), table_name='chat_tool_calls')
    op.drop_index(op.f('ix_chat_tool_calls_session_id'), table_name='chat_tool_calls')
    op.drop_table('chat_tool_calls')
    op.drop_index(op.f('ix_chat_messages_turn_id'), table_name='chat_messages')
    op.drop_column('chat_messages', 'turn_id')
