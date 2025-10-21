from datetime import datetime

from bs4 import Tag

from app.services.job_searcher.listeners.base_listeners import BaseListeners

months = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}


class DouListeners(BaseListeners):
    platform_name = "Dou"
    all_jobs = "#vacancyListId > ul > li"

    job_id = "a.vt"
    title = "a.vt"
    company = "a.company"
    description = "div.sh-info"
    date = "div.date"
    link = "a.vt"

    def get_job_id(self, element):
        element = element.select_one(self.job_id)
        return element.get("href").split("/")[-2]

    def get_date(self, element: Tag):
        date_str = super().get_date(element)
        day, month_word = date_str.split()
        month = months[month_word]
        dt = datetime(2025, month, int(day))
        return dt

    def get_link(self, element: Tag):
        select_element = element.select_one(self.link)
        if not select_element:
            raise Exception("No link found")
        return select_element.get("href")
