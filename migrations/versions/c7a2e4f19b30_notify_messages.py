"""notify messages

Revision ID: c7a2e4f19b30
Revises: b3d41c7e9a20
Create Date: 2026-11-19 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'c7a2e4f19b30'
down_revision: str | None = 'b3d41c7e9a20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('notify_messages',
    sa.Column('message_id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('project', sa.String(length=80), nullable=False),
    sa.Column('repo', sa.String(length=80), nullable=True),
    sa.Column('session', sa.String(length=128), nullable=False),
    sa.Column('sent_at', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('message_id')
    )
    with op.batch_alter_table('notify_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notify_messages_project'), ['project'], unique=False)
        batch_op.create_index(batch_op.f('ix_notify_messages_sent_at'), ['sent_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_notify_messages_session'), ['session'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('notify_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notify_messages_session'))
        batch_op.drop_index(batch_op.f('ix_notify_messages_sent_at'))
        batch_op.drop_index(batch_op.f('ix_notify_messages_project'))

    op.drop_table('notify_messages')
