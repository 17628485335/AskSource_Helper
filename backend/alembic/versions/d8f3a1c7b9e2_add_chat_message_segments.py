"""add chat_messages.segments

Revision ID: d8f3a1c7b9e2
Revises: 49f7e1d08ae0
Create Date: 2026-11-26 09:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8f3a1c7b9e2'
down_revision: Union[str, None] = '49f7e1d08ae0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 不设 server_default：新行为只在 chat 落库时写入，老消息保持 NULL；
    # 前端渲染仍读 content，因此无需回填历史数据。
    op.add_column('chat_messages', sa.Column('segments', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_messages', 'segments')
