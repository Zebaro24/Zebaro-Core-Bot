from datetime import datetime

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners

# TODO: Year is hardcoded to "2025" via string split. Should derive year
#       dynamically from the current date.

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


class JoobleListeners(BaseListeners):
    platform_name = "Jooble"
    all_jobs = 'div.infinite-scroll-component > div > ul > li > div[data-test-name="_jobCard"]'

    job_id = "pass"
    title = "h2"
    company = 'p[data-test-name="_companyName"]'
    description = "div:nth-child(2) > div > div"
    date = "div:nth-child(2) > div > div"
    link = "a"

    def get_job_id(self, element: Tag) -> str | None:
        val = element.get("id")
        return str(val) if val is not None else None

    def get_description(self, element: Tag) -> str | None:
        text = super().get_description(element)
        if not text:
            return None
        text = text.replace("\n", "").replace("  ", " ")
        if "віддалено" in text:
            return text.split("віддалено")[1].strip()
        return text

    def get_date(self, element: Tag) -> datetime | None:
        raw = super().get_date(element)
        if not isinstance(raw, str) or not raw[0].isdigit():
            return None
        date_str = raw.split("2025")[0].strip() + " 2025"  # TODO: hardcoded year
        day, month_word, year = date_str.split()
        return datetime(int(year), _MONTHS[month_word], int(day))

    def get_link(self, element: Tag) -> str:
        el = element.select_one(self.link)
        if not el:
            raise ValueError("No link found in Jooble job")
        return str(el.get("href", ""))
