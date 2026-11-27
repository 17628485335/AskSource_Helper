"""normalize context size to available options

Revision ID: d4e8f2a6b0c9
Revises: f3a9c1d5e7b2
Create Date: 2026-11-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4e8f2a6b0c9'
down_revision: Union[str, None] = 'f3a9c1d5e7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 下拉框只保留 200K / 1M：已下线的 8K~128K 旧值统一提到 200K，
    # 否则界面显示 200K、后端却仍按旧窗口裁剪历史
    op.execute("UPDATE llm_providers SET context_size = 200000 WHERE context_size < 200000")


def downgrade() -> None:
    # 旧值无法还原，留空即可
    pass
