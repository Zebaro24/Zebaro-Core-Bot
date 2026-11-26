"""The vacancies in SQL: one row per stored vacancy, its status events, its Telegram outbox.

Moved from MongoDB on 2026-11 with every value kept; the layout is the document's, cleaned up:

* `jobs` — the vacancy, what the filter and the CV routing made of it, its current status. The
  status columns are what `status.py` writes together with an event; `history` is older than some
  of them, so they are stored, not derived.
* `seen_before` — the "seen before" note of the card (the earlier copy's id, platform, when, its
  state then, opened or not), one JSON value: it is shown, never queried.
* `job_events` — the old `history` array, one row per event in its order (`position`).
* `job_sync` — the old `tg_sync` sub-document: which status change Telegram still has to show.

Times are naive UTC datetimes, as the bot computes them (`datetime.utcnow()`), not Unix ints like
the other SQL tables: vacancy times carry milliseconds and are compared in queries everywhere.
Ids are the 24-hex strings MongoDB gave them (`sql.new_id` for new ones).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.sql import Base, Json

ID = String(24)


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    # The vacancy as the board shows it.
    platform_name: Mapped[str | None] = mapped_column(String(40))
    job_id: Mapped[str | None] = mapped_column(String(120))  # the board's own id
    title: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    date: Mapped[datetime | None] = mapped_column(DateTime)  # posted, as the board says
    link: Mapped[str | None] = mapped_column(Text)
    found_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # The card's details (extract.py).
    work_format: Mapped[str | None] = mapped_column(String(32))
    countries: Mapped[str | None] = mapped_column(Text)
    english: Mapped[str | None] = mapped_column(String(16))
    salary: Mapped[str | None] = mapped_column(Text)
    applicants: Mapped[int | None] = mapped_column(Integer)
    required_years: Mapped[int | None] = mapped_column(Integer)
    warnings: Mapped[list[str] | None] = mapped_column(Json)
    search_url: Mapped[str | None] = mapped_column(Text)
    # The filter (filter.py).
    moderation: Mapped[str | None] = mapped_column(String(32))
    relevance_score: Mapped[int | None] = mapped_column(Integer)
    filter_reason: Mapped[str | None] = mapped_column(Text)
    matched_stack: Mapped[list[str] | None] = mapped_column(Json)
    matched_bonus: Mapped[list[str] | None] = mapped_column(Json)
    # The CV routing (cv.py).
    cv_track: Mapped[str | None] = mapped_column(String(32))
    cv_match: Mapped[list[str] | None] = mapped_column(Json)
    cv_gaps: Mapped[list[str] | None] = mapped_column(Json)
    cv_gaps_plus: Mapped[list[str] | None] = mapped_column(Json)
    cv_sent: Mapped[str | None] = mapped_column(String(32))
    # The current status (status.py writes these with each event).
    user_status: Mapped[str | None] = mapped_column(String(32))
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    status_reason: Mapped[str | None] = mapped_column(String(64))
    status_reason_text: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(32))
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime)
    # One vacancy on several boards (dedup.py).
    group_id: Mapped[str | None] = mapped_column(ID, ForeignKey("jobs.id"))
    copies: Mapped[list[dict[str, Any]] | None] = mapped_column(Json)
    seen_before: Mapped[dict[str, Any] | None] = mapped_column(Json)  # was similar_*; SIMILAR is reserved
    company_history: Mapped[list[dict[str, Any]] | None] = mapped_column(Json)
    click_count: Mapped[int | None] = mapped_column(Integer)
    # Its message in Telegram, and the 👀 summary of the day it was shown in.
    tg_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    tg_message_kind: Mapped[str | None] = mapped_column(String(16))
    review_day: Mapped[str | None] = mapped_column(String(10))
    review_stale: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (
        # The Jobs API pages newest first by (found_at, id).
        Index("ix_jobs_found", "found_at", "id"),
        Index("ix_jobs_group", "group_id"),
        Index("ix_jobs_board_id", "platform_name", "job_id"),
        Index("ix_jobs_review_stale", "review_stale"),
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    job_id: Mapped[str] = mapped_column(ID, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    suggested_code: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    approximate: Mapped[bool | None] = mapped_column(Boolean)
    from_reason_code: Mapped[str | None] = mapped_column(String(64))
    from_reason: Mapped[str | None] = mapped_column(Text)
    cause: Mapped[str | None] = mapped_column(String(32))  # the event that closed this copy
    restored: Mapped[bool | None] = mapped_column(Boolean)
    undo_of: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        Index("ix_job_events_order", "job_id", "position", unique=True),
        Index("ix_job_events_occurred", "occurred_at"),
        Index("ix_job_events_cause", "cause"),
    )


class JobSync(Base):
    __tablename__ = "job_sync"

    job_id: Mapped[str] = mapped_column(ID, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)  # "pending" | "done"
    event_id: Mapped[str | None] = mapped_column(String(32))
    notify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_at: Mapped[datetime | None] = mapped_column(DateTime)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("ix_job_sync_due", "state", "next_at"),)


class ReviewSummary(Base):
    """The day's 👀 summary in Telegram: its message parts, {ids, chat_id, message_id, kind}."""

    __tablename__ = "review_summaries"

    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    parts: Mapped[list[dict[str, Any]]] = mapped_column(Json, nullable=False)


class AiNoteMessage(Base):
    """One message of the AI notes in Telegram and the status events it lists, {job_id, event_id}."""

    __tablename__ = "ai_note_messages"

    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # Telegram's
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entries: Mapped[list[dict[str, Any]]] = mapped_column(Json, nullable=False)
