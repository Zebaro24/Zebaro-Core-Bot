from app.services.job_searcher.job_container import Job, JobStorage


class JobFilter:
    def __init__(self, job_storage: JobStorage):
        self.job_storage = job_storage

    def filter_all(self):
        for job in list(self.job_storage.jobs):
            skip_list_bool = [
                self.filter_seniors(job),
                self.filter_with_title(job),
                self.filter_without_title(job),
                self.filter_without_company(job),
            ]
            if any(skip_list_bool):
                self.job_storage.remove_job(job)

    @staticmethod
    def filter_seniors(job: Job) -> bool:
        if job.title is None:
            return False
        if "senior" in job.title.lower() or "middle" in job.title.lower():
            if "junior" not in job.title.lower():
                return True
        return False

    @staticmethod
    def filter_with_title(job: Job) -> bool:
        if job.title is None:
            return False
        with_list = [
            "python",
            "full",
        ]
        return not any([with_str in job.title.lower() for with_str in with_list])

    @staticmethod
    def filter_without_title(job: Job) -> bool:
        if job.title is None:
            return False
        without_list = [
            "odoo",
            "викладач",
            "тренер",
            "lead",
            "qa",
        ]
        return any([without_str in job.title.lower() for without_str in without_list])

    @staticmethod
    def filter_without_company(job: Job) -> bool:
        if job.company is None:
            return False
        without_list = ["фоп", "school"]
        return any([without_str in job.company.lower() for without_str in without_list])
