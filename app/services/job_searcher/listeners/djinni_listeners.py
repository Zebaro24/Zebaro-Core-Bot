from datetime import datetime

from bs4 import Tag

from app.services.job_searcher.listeners.base_listeners import BaseListeners


class DjinniListeners(BaseListeners):
    platform_name = "Djinni"
    all_jobs = "ul.list-jobs > li"

    job_id = "pass"
    title = "h2"
    company = 'a[data-analytics="company_page"]'
    description = "span.js-truncated-text"
    date = 'span.text-nowrap[data-toggle="tooltip"]'
    link = "a.job-item__title-link"

    def get_job_id(self, element):
        id_str = element.get("id")
        if not id_str:
            raise Exception("No job id found")
        return id_str.split("-")[-1]

    def get_date(self, element: Tag):
        select_element = element.select_one(self.date)
        if not select_element:
            raise Exception("No date found")
        date_str = select_element.get("data-original-title")
        if not date_str or not isinstance(date_str, str):
            raise Exception("No date found")
        dt = datetime.strptime(date_str, "%H:%M %d.%m.%Y")
        return dt

    def get_link(self, element: Tag):
        select_element = element.select_one(self.link)
        if not select_element:
            raise Exception("No link found")
        return f"https://djinni.co{select_element.get('href')}"
