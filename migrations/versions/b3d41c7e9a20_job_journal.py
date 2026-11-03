"""job journal

Revision ID: b3d41c7e9a20
Revises: 9f860b05eacb
Create Date: 2026-11-03 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'b3d41c7e9a20'
down_revision: str | None = '9f860b05eacb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('job_journal',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('occurred_at', sa.BigInteger(), nullable=False),
    sa.Column('recorded_at', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('actor', sa.String(length=16), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('job_journal', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_journal_occurred_at'), ['occurred_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('job_journal', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_journal_occurred_at'))

    op.drop_table('job_journal')
