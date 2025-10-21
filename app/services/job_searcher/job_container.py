from dataclasses import asdict, dataclass

from app.db.client import jobs_collection


@dataclass
class Job:
    platform_name: str = None
    job_id: str = None
    title: str = None
    company: str = None
    description: str = None
    date: str = None
    link: str = None

    def print_job(self):
        print(f"Platform Name: {self.platform_name}")
        print(f"Job ID: {self.job_id}")
        print(f"Title: {self.title}")
        print(f"Company: {self.company}")
        print(f"Description: {self.description}")
        print(f"Date: {self.date}")
        print(f"Link: {self.link}")

    def __str__(self):
        return f"<{self.platform_name} - {self.title} - {self.company}>"


class JobStorage:
    def __init__(self):
        self.jobs: list[Job] = []

    def add_job(self, job):
        self.jobs.append(job)

    def remove_job(self, job):
        print(f"Removed {job}")
        self.jobs.remove(job)

    async def save_jobs_to_db(self):
        if not self.jobs:
            return

        docs = [asdict(job) for job in self.jobs]
        await jobs_collection.insert_many(docs)

    async def remove_jobs_already_in_db(self):
        for job in list(self.jobs):
            exists = await jobs_collection.count_documents(
                {"platform_name": job.platform_name, "job_id": job.job_id}, limit=1
            )
            if exists:
                self.jobs.remove(job)

    def print_jobs(self):
        print("<" + f" Всего {len(self.jobs)} вакансий ".center(38, "-") + ">")
        for job in self.jobs:
            job.print_job()
            print("----------------------------------------")
