"""add llm provider context size

Revision ID: f3a9c1d5e7b2
Revises: c7d2e5a4b9f3
Create Date: 2026-11-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a9c1d5e7b2'
down_revision: Union[str, None] = 'a1d4e7b9c2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('llm_providers', sa.Column('context_size', sa.Integer(), nullable=True))
    op.execute("UPDATE llm_providers SET context_size = 32768 WHERE context_size IS NULL")
    # 与 ORM 的客户端默认值保持一致，不设 server_default（避免 alembic check 漂移）
    op.alter_column('llm_providers', 'context_size', existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    op.drop_column('llm_providers', 'context_size')
