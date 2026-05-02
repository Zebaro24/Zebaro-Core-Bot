import logging
from dataclasses import asdict, dataclass
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
    date: str | datetime | None = None
    link: str | None = None

    def __str__(self) -> str:
        return f"<{self.platform_name} - {self.title} - {self.company}>"


class JobStorage:
    def __init__(self) -> None:
        self.jobs: list[Job] = []

    def add_job(self, job: Job) -> None:
        self.jobs.append(job)

    def remove_job(self, job: Job) -> None:
        self.jobs.remove(job)
        logger.debug("Removed job: %s", job)

    async def save_jobs_to_db(self) -> None:
        if not self.jobs:
            logger.info("No new jobs to save")
            return
        try:
            docs = [asdict(job) for job in self.jobs]
            await jobs_collection.insert_many(docs)
            logger.info("Saved %d jobs to DB", len(docs))
        except Exception as e:
            logger.warning("Failed to save jobs to DB (running without DB): %s", e)

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
