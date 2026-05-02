from datetime import datetime

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners


class DjinniListeners(BaseListeners):
    platform_name = "Djinni"
    all_jobs = "ul.list-jobs > li"

    job_id = "pass"
    title = "h2"
    company = 'a[data-analytics="company_page"]'
    description = "span.js-truncated-text"
    date = 'span.text-nowrap[data-toggle="tooltip"]'
    link = "a.job-item__title-link"

    def get_job_id(self, element: Tag) -> str:
        id_str = element.get("id")
        if not id_str:
            raise ValueError("No job id found in Djinni element")
        return str(id_str).split("-")[-1]

    def get_date(self, element: Tag) -> datetime:
        select_element = element.select_one(self.date)
        if not select_element:
            raise ValueError("No date element found in Djinni job")
        date_str = select_element.get("data-original-title")
        if not date_str or not isinstance(date_str, str):
            raise ValueError("No date string found in Djinni element")
        return datetime.strptime(date_str, "%H:%M %d.%m.%Y")

    def get_link(self, element: Tag) -> str:
        select_element = element.select_one(self.link)
        if not select_element:
            raise ValueError("No link found in Djinni job")
        return f"https://djinni.co{select_element.get('href')}"
