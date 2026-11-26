import logging
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, or_

from src.services.job_searcher import store
from src.services.job_searcher.store import J

logger = logging.getLogger("job_searcher.container")

# A stored id hides the vacancy from every later run — unless that copy is older than this and
# the owner never answered it (05.11.2026). PwC's full-stack position, stored in 11.2025 without a
# decision, was live and bumped a year later and never came; two months is about when a hire
# passes probation and a position opens again.
REVISIT_DAYS = 60


def already_seen_query(platform_name: str | None, job_id: str | None, now: datetime) -> ColumnElement[bool]:
    """A stored copy that still hides the vacancy: answered, or found within REVISIT_DAYS.

    A "duplicate" is not an answer: same-run copies are marked so whether or not anyone answered.
    A repeat of an answered vacancy is caught again by the grouping (dedup.py), within its
    LOOKBACK_DAYS. `found_at` is the insert time (it was the ObjectId's in MongoDB — equal for all)."""
    since = now - timedelta(days=REVISIT_DAYS)
    return and_(
        store.eq(J.platform_name, platform_name),
        store.eq(J.job_id, job_id),
        or_(store.not_in(J.user_status, [None, "pending", "duplicate"]), J.found_at >= since),
    )


async def known_count(platform_name: str | None, job_ids: list[str]) -> int:
    """How many of these ids are stored already (0 when the DB cannot say). Distinct ids: one id
    may be stored more than once (a revisit after REVISIT_DAYS, old same-run copies)."""
    if not job_ids:
        return 0
    try:
        return len(
            await store.distinct(J.job_id, and_(store.eq(J.platform_name, platform_name), J.job_id.in_(job_ids)))
        )
    except Exception as e:
        logger.warning("DB unavailable for the known-ids check: %s", e)
        return 0


@dataclass
class Job:
    platform_name: str | None = None
    job_id: str | None = None
    title: str | None = None
    company: str | None = None
    description: str | None = None
    location: str | None = None  # as the site writes it: "Remote only • Everywhere", "Київ"
    date: str | datetime | None = None
    link: str | None = None

    found_at: datetime = field(default_factory=datetime.utcnow)
    moderation: str | None = None  # "top" | "sent" | "review" | "rejected_by_filter"
    relevance_score: int = 0
    # "pending" | "applied" | "mismatch" (he does not meet the requirements) | "not_interested" |
    # "blocked" (the site would not let him apply — Djinni's profile gate) | "duplicate" (a
    # repeat of a group already sent: never counted)
    user_status: str = "pending"
    status_updated_at: datetime | None = None
    similar_to: str | None = None  # id похожей вакансии на другой площадке
    similar_to_platform: str | None = None  # платформа этой похожей вакансии (для бейджа в Telegram)
    similar_seen_at: datetime | None = None  # when that earlier copy was found
    similar_status: str | None = None  # the group's state then: "pending" | "blocked"
    similar_clicked: bool = False  # the owner opened the link of that earlier copy
    # The company's other vacancies the owner answered or opened, newest first:
    # {title, status, at, platform, similar} — "similar" when the title is close to this one.
    company_history: list[dict] = field(default_factory=list)
    group_id: str | None = None  # id of the first vacancy of this group
    copies: list[dict] = field(default_factory=list)  # the same vacancy on other sites: {platform, id}
    click_count: int = 0
    matched_stack: list[str] = field(default_factory=list)  # core stack found: "Python", "React", ...
    matched_bonus: list[str] = field(default_factory=list)  # nice-to-have found: "TypeScript", "LLM", ...
    required_years: int | None = None  # the main experience requirement (card or description)
    filter_reason: str | None = None  # why it was not sent: "senior", "experience", "office", ...

    # What the board says apart from the text (Djinni's card, DOU's cities) or what was read
    # out of the description — services/job_searcher/extract.py.
    work_format: str | None = None  # "remote" | "office" | "hybrid" | "office_or_remote"
    countries: str | None = None  # where candidates may live, as the site writes it
    english: str | None = None  # "A1".."C2", "none"
    salary: str | None = None  # as the site writes it: "до $2500", "$3500–4500"
    applicants: int | None = None  # how many applied already (Djinni)
    warnings: list[str] = field(default_factory=list)  # what may not fit: "english", "ukraine", ...
    search_url: str | None = None  # the search that found it — to compare searches
    # Which of the owner's CVs the vacancy gets (services/job_searcher/cv.py): "backend" |
    # "fullstack" | "ai"; the CV's skills it names, and what it asks for that the CV lacks —
    # required (`cv_gaps`) or only "nice to have" (`cv_gaps_plus`).
    cv_track: str | None = None
    cv_match: list[str] = field(default_factory=list)
    cv_gaps: list[str] = field(default_factory=list)
    cv_gaps_plus: list[str] = field(default_factory=list)
    # The CV the application went with: the routed one when "applied" is written, changed by the
    # buttons under it; "universal" — the one CV before 09.11.2026.
    cv_sent: str | None = None
    # Why the owner said no: "experience" | "location" | "english" | "site" | "stack" (mismatch),
    # "role" | "stack" | "domain" | "conditions" | "position_closed" | "other" (not_interested).
    status_reason: str | None = None
    # After "applied": how it went — "reply" | "interview" | "offer" | "rejected".
    outcome: str | None = None
    outcome_at: datetime | None = None
    # The vacancy's own message in Telegram, to edit it when its status changes through the API
    # (Jobs API, part B). "rich" | "plain": the two are edited differently. Kept since 29.10.2026;
    # the 👀 summary's vacancies get one only when opened as their own message.
    tg_chat_id: int | None = None
    tg_message_id: int | None = None
    tg_message_kind: str | None = None

    def __str__(self) -> str:
        return f"<{self.platform_name} - {self.title} - {self.company}>"

    @classmethod
    def from_doc(cls, doc: dict) -> "Job":
        """A Job back from its stored document; unknown keys (like `_id`) are ignored, and so is None —
        a field the vacancy does not have keeps the default, as a missing key always did."""
        names = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in doc.items() if key in names and value is not None})


class JobStorage:
    def __init__(self) -> None:
        self.jobs: list[Job] = []
        self._seen: set[tuple[str | None, str | None]] = set()

    def add_job(self, job: Job) -> bool:
        """Add a vacancy unless this run already has it. Returns whether it was added.

        One vacancy shows up on several searches of the same site (DOU lists it under Python
        and Fullstack, remote and relocation, in the hot block and in the plain list), and the
        check against the DB only sees earlier runs — so without this it arrived twice.
        """
        if job.job_id is not None:
            key = (job.platform_name, job.job_id)
            if key in self._seen:
                return False
            self._seen.add(key)
        self.jobs.append(job)
        return True

    def remove_job(self, job: Job) -> None:
        self.jobs.remove(job)
        logger.debug("Removed job: %s", job)

    async def save_jobs_to_db(self) -> list[str | None]:
        if not self.jobs:
            logger.info("No new jobs to save")
            return []
        try:
            for job in self.jobs:
                if isinstance(job.date, str):  # a board's text date ("2 дні тому"): the column takes dates only
                    from src.services.job_searcher.extract import relative_date

                    text, job.date = job.date, relative_date(job.date, job.found_at)
                    if job.date is None:
                        logger.warning("Unreadable date %r of %s, stored without one", text, job)
            ids = await store.put([store.from_job(job) for job in self.jobs])
            logger.info("Saved %d jobs to DB", len(ids))
            return list(ids)
        except Exception as e:
            logger.warning("Failed to save jobs to DB (running without DB): %s", e)
            return [None] * len(self.jobs)

    async def remove_jobs_already_in_db(self) -> None:
        before = len(self.jobs)
        now = datetime.utcnow()
        try:
            for job in list(self.jobs):
                if await store.count(already_seen_query(job.platform_name, job.job_id, now)):
                    self.jobs.remove(job)
            removed = before - len(self.jobs)
            if removed:
                logger.info("Removed %d already-seen jobs from storage", removed)
        except Exception as e:
            logger.warning("DB unavailable for dedup check, skipping: %s", e)

    def log_jobs(self) -> None:
        logger.info("Total new jobs: %d", len(self.jobs))
        for job in self.jobs:
            logger.debug("  %s", job)


async def remember_message(job_id: str, chat_id: int, message_id: int, kind: str) -> None:
    """Store which Telegram message shows the vacancy; the latest one wins."""
    try:
        await store.update(job_id, {"tg_chat_id": chat_id, "tg_message_id": message_id, "tg_message_kind": kind})
    except Exception as e:  # the message is out already; only a later edit is lost
        logger.warning("Could not store the Telegram message of vacancy %s: %s", job_id, e)
