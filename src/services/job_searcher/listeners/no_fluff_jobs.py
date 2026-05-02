from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners


class NoFluffJobsListeners(BaseListeners):
    platform_name = "No Fluff Jobs"
    all_jobs = "div.list-container > a"

    job_id = "pass"
    title = "h3"
    company = "h4"
    description = "pass"
    date = "pass"
    link = "pass"

    def get_job_id(self, element: Tag) -> str | None:
        val = element.get("id")
        return str(val) if val is not None else None

    def get_link(self, element: Tag) -> str:
        return f"https://nofluffjobs.com{str(element.get('href', ''))}"
