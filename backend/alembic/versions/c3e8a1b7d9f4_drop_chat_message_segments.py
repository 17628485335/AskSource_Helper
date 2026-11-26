"""drop chat_messages.segments

Revision ID: c3e8a1b7d9f4
Revises: f2a7c4e9b1d3
Create Date: 2026-11-26 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e8a1b7d9f4'
down_revision: Union[str, None] = 'f2a7c4e9b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 正文已由 content 承载，工具调用已拆到 chat_tool_calls，无需再存分段 JSON
    op.drop_column('chat_messages', 'segments')


def downgrade() -> None:
    op.add_column('chat_messages', sa.Column('segments', sa.JSON(), nullable=True))
