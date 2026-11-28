"""add user_id to agent_memories

Revision ID: e9f4a7c2d6b1
Revises: b8d4f0a3e5c2
Create Date: 2026-11-28 00:00:00.000000

user_id=0 表示 agent 全局记忆；已有数据迁移后保持全局可见。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9f4a7c2d6b1'
down_revision: Union[str, None] = 'b8d4f0a3e5c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'agent_memories',
        sa.Column('user_id', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )
    op.create_index(
        op.f('ix_agent_memories_user_id'), 'agent_memories', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_memories_user_id'), table_name='agent_memories')
    op.drop_column('agent_memories', 'user_id')
