from datetime import datetime

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners


class WorkUAListeners(BaseListeners):
    platform_name = "Work.ua"
    all_jobs = "#pjax-jobs-list > .job-link"

    job_id = "pass"
    title = "div > h2 > a"
    company = "div > span > span"
    description = "div > p"
    date = "div > time"
    link = "pass"

    def get_job_id(self, element: Tag) -> str:
        el = element.select_one("div > h2 > a")
        if not el or not el.get("href"):
            raise ValueError("No job id found in Work.ua element")
        return str(el.get("href")).split("/")[-2]

    def get_description(self, element: Tag) -> str | None:
        text = super().get_description(element)
        if not text:
            return None
        lines = text.split("\n")
        return lines[1].strip() if len(lines) > 1 else text.strip()

    def get_date(self, element: Tag) -> datetime | None:
        datetime_element = element.select_one(self.date)
        if not datetime_element:
            return None
        datetime_str = datetime_element.get("datetime")
        if not datetime_str or not isinstance(datetime_str, str):
            raise ValueError("No datetime attribute in Work.ua element")
        return datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")

    def get_link(self, element: Tag) -> str:
        return f"https://www.work.ua/jobs/{self.get_job_id(element)}"
