"""add user nickname and avatar

Revision ID: c7d2e5a4b9f3
Revises: b7c5d3e8f1a2
Create Date: 2026-11-26 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7d2e5a4b9f3'
down_revision: Union[str, None] = 'b7c5d3e8f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先可空加列并回填，再收紧为 NOT NULL：避免旧数据直接加非空列失败
    op.add_column('users', sa.Column('nickname', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('avatar', sa.Text(), nullable=True))
    op.execute("UPDATE users SET nickname = username WHERE nickname IS NULL OR nickname = ''")
    op.execute("UPDATE users SET avatar = '' WHERE avatar IS NULL")
    # 与 auth.models.User 保持一致：只用 ORM 客户端默认值，不设 server_default（避免 alembic check 漂移）
    op.alter_column('users', 'nickname', existing_type=sa.String(length=64), nullable=False)
    op.alter_column('users', 'avatar', existing_type=sa.Text(), nullable=False)


def downgrade() -> None:
    op.drop_column('users', 'avatar')
    op.drop_column('users', 'nickname')
