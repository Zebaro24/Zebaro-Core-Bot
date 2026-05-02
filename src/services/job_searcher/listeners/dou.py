from datetime import datetime

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners

# TODO: Year is hardcoded to 2025 in get_date(). Should use current year
#       (datetime.now().year) to avoid breakage in future years.

_MONTHS = {
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

    def get_job_id(self, element: Tag) -> str:
        el = element.select_one(self.job_id)
        if not el:
            raise ValueError("No job id found in Dou element")
        return str(el.get("href")).split("/")[-2]

    def get_date(self, element: Tag) -> datetime:
        date_str = super().get_date(element)
        if not isinstance(date_str, str):
            raise ValueError("No date string found in Dou element")
        day, month_word = date_str.split()
        return datetime(2025, _MONTHS[month_word], int(day))  # TODO: hardcoded year

    def get_link(self, element: Tag) -> str:
        el = element.select_one(self.link)
        if not el:
            raise ValueError("No link found in Dou job")
        return str(el.get("href"))
