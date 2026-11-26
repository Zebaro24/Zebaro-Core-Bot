"""postgres: jobs, events, outbox, kv, vpn — the MongoDB collections as tables

The JSON columns are JSONB on PostgreSQL (src.db.sql.Json adds the datetime round trip in Python;
the stored type is plain JSON, so it is spelled out here instead of importing the model's type).

Revision ID: e5f1a9c3b7d2
Revises: d4e8a1c27f51
Create Date: 2026-11-26 14:28:51.821687
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = 'e5f1a9c3b7d2'
down_revision: str | None = 'd4e8a1c27f51'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table('ai_note_messages',
    sa.Column('message_id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('entries', JSON, nullable=False),
    sa.PrimaryKeyConstraint('message_id')
    )
    op.create_table('jobs',
    sa.Column('id', sa.String(length=24), nullable=False),
    sa.Column('platform_name', sa.String(length=40), nullable=True),
    sa.Column('job_id', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('company', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('date', sa.DateTime(), nullable=True),
    sa.Column('link', sa.Text(), nullable=True),
    sa.Column('found_at', sa.DateTime(), nullable=False),
    sa.Column('work_format', sa.String(length=32), nullable=True),
    sa.Column('countries', sa.Text(), nullable=True),
    sa.Column('english', sa.String(length=16), nullable=True),
    sa.Column('salary', sa.Text(), nullable=True),
    sa.Column('applicants', sa.Integer(), nullable=True),
    sa.Column('required_years', sa.Integer(), nullable=True),
    sa.Column('warnings', JSON, nullable=True),
    sa.Column('search_url', sa.Text(), nullable=True),
    sa.Column('moderation', sa.String(length=32), nullable=True),
    sa.Column('relevance_score', sa.Integer(), nullable=True),
    sa.Column('filter_reason', sa.Text(), nullable=True),
    sa.Column('matched_stack', JSON, nullable=True),
    sa.Column('matched_bonus', JSON, nullable=True),
    sa.Column('cv_track', sa.String(length=32), nullable=True),
    sa.Column('cv_match', JSON, nullable=True),
    sa.Column('cv_gaps', JSON, nullable=True),
    sa.Column('cv_gaps_plus', JSON, nullable=True),
    sa.Column('cv_sent', sa.String(length=32), nullable=True),
    sa.Column('user_status', sa.String(length=32), nullable=True),
    sa.Column('status_updated_at', sa.DateTime(), nullable=True),
    sa.Column('status_reason', sa.String(length=64), nullable=True),
    sa.Column('status_reason_text', sa.Text(), nullable=True),
    sa.Column('outcome', sa.String(length=32), nullable=True),
    sa.Column('outcome_at', sa.DateTime(), nullable=True),
    sa.Column('group_id', sa.String(length=24), nullable=True),
    sa.Column('copies', JSON, nullable=True),
    sa.Column('seen_before', JSON, nullable=True),
    sa.Column('company_history', JSON, nullable=True),
    sa.Column('click_count', sa.Integer(), nullable=True),
    sa.Column('tg_chat_id', sa.BigInteger(), nullable=True),
    sa.Column('tg_message_id', sa.BigInteger(), nullable=True),
    sa.Column('tg_message_kind', sa.String(length=16), nullable=True),
    sa.Column('review_day', sa.String(length=10), nullable=True),
    sa.Column('review_stale', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['group_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index('ix_jobs_board_id', ['platform_name', 'job_id'], unique=False)
        batch_op.create_index('ix_jobs_found', ['found_at', 'id'], unique=False)
        batch_op.create_index('ix_jobs_group', ['group_id'], unique=False)
        batch_op.create_index('ix_jobs_review_stale', ['review_stale'], unique=False)

    op.create_table('kv',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', JSON, nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('review_summaries',
    sa.Column('day', sa.String(length=10), nullable=False),
    sa.Column('parts', JSON, nullable=False),
    sa.PrimaryKeyConstraint('day')
    )
    op.create_table('vpn_clients',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('ipv4', sa.String(length=15), nullable=True),
    sa.Column('last_rx', sa.BigInteger(), nullable=True),
    sa.Column('last_tx', sa.BigInteger(), nullable=True),
    sa.Column('total_rx', sa.BigInteger(), nullable=True),
    sa.Column('total_tx', sa.BigInteger(), nullable=True),
    sa.Column('seen_at', sa.DateTime(), nullable=True),
    sa.Column('first_connected_at', sa.DateTime(), nullable=True),
    sa.Column('expiry_noticed_for', sa.String(length=40), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('vpn_traffic_daily',
    sa.Column('client_id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('day', sa.String(length=10), nullable=False),
    sa.Column('rx', sa.BigInteger(), nullable=False),
    sa.Column('tx', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('client_id', 'day')
    )
    op.create_table('job_events',
    sa.Column('job_id', sa.String(length=24), nullable=False),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(), nullable=True),
    sa.Column('recorded_at', sa.DateTime(), nullable=True),
    sa.Column('from_status', sa.String(length=32), nullable=True),
    sa.Column('to_status', sa.String(length=32), nullable=True),
    sa.Column('actor', sa.String(length=16), nullable=True),
    sa.Column('reason_code', sa.String(length=64), nullable=True),
    sa.Column('suggested_code', sa.String(length=64), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('evidence', sa.Text(), nullable=True),
    sa.Column('approximate', sa.Boolean(), nullable=True),
    sa.Column('from_reason_code', sa.String(length=64), nullable=True),
    sa.Column('from_reason', sa.Text(), nullable=True),
    sa.Column('cause', sa.String(length=32), nullable=True),
    sa.Column('restored', sa.Boolean(), nullable=True),
    sa.Column('undo_of', sa.String(length=32), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('job_id', 'id')
    )
    with op.batch_alter_table('job_events', schema=None) as batch_op:
        batch_op.create_index('ix_job_events_cause', ['cause'], unique=False)
        batch_op.create_index('ix_job_events_occurred', ['occurred_at'], unique=False)
        batch_op.create_index('ix_job_events_order', ['job_id', 'position'], unique=True)

    op.create_table('job_sync',
    sa.Column('job_id', sa.String(length=24), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('event_id', sa.String(length=32), nullable=True),
    sa.Column('notify', sa.Boolean(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_at', sa.DateTime(), nullable=True),
    sa.Column('settled_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('job_id')
    )
    with op.batch_alter_table('job_sync', schema=None) as batch_op:
        batch_op.create_index('ix_job_sync_due', ['state', 'next_at'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('job_sync', schema=None) as batch_op:
        batch_op.drop_index('ix_job_sync_due')

    op.drop_table('job_sync')
    with op.batch_alter_table('job_events', schema=None) as batch_op:
        batch_op.drop_index('ix_job_events_order')
        batch_op.drop_index('ix_job_events_occurred')
        batch_op.drop_index('ix_job_events_cause')

    op.drop_table('job_events')
    op.drop_table('vpn_traffic_daily')
    op.drop_table('vpn_clients')
    op.drop_table('review_summaries')
    op.drop_table('kv')
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index('ix_jobs_review_stale')
        batch_op.drop_index('ix_jobs_group')
        batch_op.drop_index('ix_jobs_found')
        batch_op.drop_index('ix_jobs_board_id')

    op.drop_table('jobs')
    op.drop_table('ai_note_messages')
