"""github app: forum topics, repos with levels, live messages

Revision ID: d4e8a1c27f51
Revises: c7a2e4f19b30
Create Date: 2026-11-26 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'd4e8a1c27f51'
down_revision: str | None = 'c7a2e4f19b30'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('github_topics',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('thread_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('chat_id', 'thread_id')
    )
    op.create_table('github_repos',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('full_name', sa.String(length=140), nullable=False),
    sa.Column('level', sa.String(length=8), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['topic_id'], ['github_topics.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('full_name')
    )
    op.create_table('github_messages',
    sa.Column('key', sa.String(length=220), nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('message_id', sa.BigInteger(), nullable=False),
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('sent_at', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    with op.batch_alter_table('github_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_github_messages_message_id'), ['message_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_github_messages_sent_at'), ['sent_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('github_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_github_messages_sent_at'))
        batch_op.drop_index(batch_op.f('ix_github_messages_message_id'))

    op.drop_table('github_messages')
    op.drop_table('github_repos')
    op.drop_table('github_topics')
