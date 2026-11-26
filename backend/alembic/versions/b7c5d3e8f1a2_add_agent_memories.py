"""add agent memories

Revision ID: b7c5d3e8f1a2
Revises: a9f4c2d7e6b8
Create Date: 2026-11-26 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c5d3e8f1a2'
down_revision: Union[str, None] = 'a9f4c2d7e6b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_memories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_memories_agent_id'), 'agent_memories', ['agent_id'], unique=False)
    op.create_index(op.f('ix_agent_memories_enabled'), 'agent_memories', ['enabled'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_memories_enabled'), table_name='agent_memories')
    op.drop_index(op.f('ix_agent_memories_agent_id'), table_name='agent_memories')
    op.drop_table('agent_memories')
