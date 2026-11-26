"""reorder context bindings and align trust levels

Revision ID: e7b9c1a4d6f2
Revises: c7d2e5a4b9f3
Create Date: 2026-11-26 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7b9c1a4d6f2'
down_revision: Union[str, None] = 'c7d2e5a4b9f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_ORDER = (
    ('identity', 10, 'anchor'),
    ('soul', 20, 'policy'),
    ('agents_guide', 30, 'policy'),
    ('skills_snapshot', 40, 'generated'),
    ('user_profile', 50, 'data'),
    ('long_term_memory', 60, 'data'),
)

OLD_ORDER = (
    ('skills_snapshot', 10, 'generated'),
    ('soul', 20, 'policy'),
    ('identity', 30, 'policy'),
    ('agents_guide', 40, 'policy'),
    ('user_profile', 50, 'data'),
    ('long_term_memory', 60, 'data'),
)


def _apply(rows: Sequence[tuple[str, int, str]]) -> None:
    stmt = sa.text(
        "UPDATE agent_context_bindings "
        "SET priority = :priority, trust_level = :trust_level "
        "WHERE `key` = :key"
    )
    for key, priority, trust_level in rows:
        op.execute(
            stmt.bindparams(key=key, priority=priority, trust_level=trust_level)
        )


def upgrade() -> None:
    _apply(NEW_ORDER)


def downgrade() -> None:
    _apply(OLD_ORDER)
