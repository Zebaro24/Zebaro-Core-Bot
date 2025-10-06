from bs4 import Tag

from app.services.job_searcher.listeners.base_listeners import BaseListeners

class NoFluffJobsListeners(BaseListeners):
    platform_name = "No Fluff Jobs"
    all_jobs = "div.list-container > a"

    job_id = "pass"
    title = "h3"
    company = "h4"
    description = "pass"
    date = "pass"
    link = "pass"

    def get_job_id(self, element):
        return element.get("id")

    def get_link(self, element: Tag):
        return f"https://nofluffjobs.com{element.get('href')}"