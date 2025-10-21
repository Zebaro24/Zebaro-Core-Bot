from datetime import datetime

from bs4 import Tag

from app.services.job_searcher.listeners.base_listeners import BaseListeners


class WorkUAListeners(BaseListeners):
    platform_name = "Work.ua"
    all_jobs = "#pjax-jobs-list > .job-link"

    job_id = "pass"
    title = "div > h2 > a"
    company = "div > span > span"
    description = "div > p"
    date = "div > time"
    link = "pass"

    def get_job_id(self, element):
        element = element.select_one("div > h2 > a")
        if not element or not element.get("href"):
            raise Exception("No job id found")
        return element.get("href").split("/")[-2]

    def get_description(self, element: Tag):
        text = super().get_description(element)
        return text.split("\n")[1].strip()

    def get_date(self, element: Tag):
        datetime_element = element.select_one(self.date)
        if not datetime_element:
            return None
        datetime_str = datetime_element.get("datetime")
        if not datetime_str:
            raise Exception("No date found")
        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
        return dt

    def get_link(self, element: Tag):
        return f"https://www.work.ua/jobs/{self.get_job_id(element)}"
