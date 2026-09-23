import logging
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

from src.db.client import jobs_collection

# TODO: JobStorage is coupled to the DB layer (jobs_collection imported directly).
#       Ideal refactoring: pass a repository interface so JobStorage stays pure
#       and the DB coupling lives in infrastructure/repositories/.

logger = logging.getLogger("job_searcher.container")


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
    moderation: str | None = None  # "sent" | "review" | "rejected_by_filter"
    relevance_score: int = 0
    user_status: str = "pending"  # "pending" | "applied" | "not_interested"
    status_updated_at: datetime | None = None
    similar_to: str | None = None  # mongo _id похожей вакансии на другой площадке
    similar_to_platform: str | None = None  # платформа этой похожей вакансии (для бейджа в Telegram)
    click_count: int = 0
    matched_stack: list[str] = field(default_factory=list)  # core stack found: "Python", "React", ...
    matched_bonus: list[str] = field(default_factory=list)  # nice-to-have found: "TypeScript", "LLM", ...
    required_years: int | None = None  # the lowest experience the description asks for
    filter_reason: str | None = None  # why it was not sent: "senior", "intern", "no stack match", ...

    def __str__(self) -> str:
        return f"<{self.platform_name} - {self.title} - {self.company}>"

    @classmethod
    def from_doc(cls, doc: dict) -> "Job":
        """A Job back from its MongoDB document; unknown keys (like `_id`) are ignored."""
        names = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in doc.items() if key in names})


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
            docs = [asdict(job) for job in self.jobs]
            result = await jobs_collection.insert_many(docs)
            logger.info("Saved %d jobs to DB", len(docs))
            return [str(_id) for _id in result.inserted_ids]
        except Exception as e:
            logger.warning("Failed to save jobs to DB (running without DB): %s", e)
            return [None] * len(self.jobs)

    async def remove_jobs_already_in_db(self) -> None:
        before = len(self.jobs)
        try:
            for job in list(self.jobs):
                exists = await jobs_collection.count_documents(
                    {"platform_name": job.platform_name, "job_id": job.job_id}, limit=1
                )
                if exists:
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
