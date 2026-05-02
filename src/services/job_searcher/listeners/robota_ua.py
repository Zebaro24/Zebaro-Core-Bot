from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners


class RobotaUAListeners(BaseListeners):
    platform_name = "Robota.ua"
    all_jobs = "alliance-vacancy-card-desktop"

    job_id = "a"
    title = "h2"
    company = "span.santa-mr-20"
    description = "pass"
    date = "div.santa-typo-secondary.santa-text-black-500"
    link = "a"

    def get_job_id(self, element: Tag) -> str:
        el = element.select_one(self.job_id)
        if not el:
            raise ValueError("No job id found in Robota.ua element")
        return str(el.get("href")).split("/")[-1][7:]

    def get_link(self, element: Tag) -> str:
        el = element.select_one(self.link)
        if not el:
            raise ValueError("No link found in Robota.ua element")
        return f"https://www.robota.ua{el.get('href')}"
