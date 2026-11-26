"""add prompt_hash to agent_prompts

Revision ID: a1d4e7b9c2f5
Revises: f3a7c9d1e5b4
Create Date: 2026-11-26 22:00:00.000000

"""
import hashlib
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1d4e7b9c2f5'
down_revision: Union[str, None] = 'f3a7c9d1e5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DATE_LINE_RE = re.compile(r"^今天是 \d{4}-\d{2}-\d{2} 周[一二三四五六日]（北京时间）。$")


def _hash(prompt: str) -> str:
    lines = (prompt or "").rstrip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and _DATE_LINE_RE.match(lines[-1].strip()):
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    stable = "\n".join(lines).rstrip()
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.add_column(
        'agent_prompts',
        sa.Column('prompt_hash', sa.String(length=64), nullable=False, server_default=''),
    )
    op.create_index('ix_agent_prompts_prompt_hash', 'agent_prompts', ['prompt_hash'])

    conn = op.get_bind()
    rows = conn.execute(sa.text('SELECT id, system_prompt FROM agent_prompts')).all()
    stmt = sa.text('UPDATE agent_prompts SET prompt_hash = :hash WHERE id = :id')
    for row in rows:
        conn.execute(stmt.bindparams(id=row.id, hash=_hash(row.system_prompt or '')))


def downgrade() -> None:
    op.drop_index('ix_agent_prompts_prompt_hash', table_name='agent_prompts')
    op.drop_column('agent_prompts', 'prompt_hash')
