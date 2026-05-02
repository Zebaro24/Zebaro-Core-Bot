import logging

from src.services.job_searcher.container import Job, JobStorage

logger = logging.getLogger("job_searcher.filter")


class JobFilter:
    def __init__(self, job_storage: JobStorage) -> None:
        self.job_storage = job_storage

    def filter_all(self) -> None:
        before = len(self.job_storage.jobs)
        for job in list(self.job_storage.jobs):
            if any(
                [
                    self.filter_seniors(job),
                    self.filter_with_title(job),
                    self.filter_without_title(job),
                    self.filter_without_company(job),
                ]
            ):
                self.job_storage.remove_job(job)
        removed = before - len(self.job_storage.jobs)
        logger.info("Filtered out %d jobs (%d remaining)", removed, len(self.job_storage.jobs))

    @staticmethod
    def filter_seniors(job: Job) -> bool:
        if not job.title:
            return False
        title = job.title.lower()
        if ("senior" in title or "middle" in title) and "junior" not in title:
            return True
        return False

    @staticmethod
    def filter_with_title(job: Job) -> bool:
        if not job.title:
            return False
        with_list = ["python", "full"]
        return not any(w in job.title.lower() for w in with_list)

    @staticmethod
    def filter_without_title(job: Job) -> bool:
        if not job.title:
            return False
        without_list = ["odoo", "викладач", "тренер", "lead", "qa"]
        return any(w in job.title.lower() for w in without_list)

    @staticmethod
    def filter_without_company(job: Job) -> bool:
        if not job.company:
            return False
        without_list = ["фоп", "school"]
        return any(w in job.company.lower() for w in without_list)
