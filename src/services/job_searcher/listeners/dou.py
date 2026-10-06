from datetime import datetime
from typing import Any

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners, resolve_year

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
    # "Київ, віддалено", "за кордоном, віддалено", "Львів" — where the job is done, and whether
    # a candidate abroad is taken at all ("за кордоном").
    location = "span.cities"
    salary = "span.salary"
    date = "div.date"
    link = "a.vt"

    detail_description = ".b-typo.vacancy-section"

    def get_details(self, element: Tag) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if salary := self._get_one_by_selector(element, self.salary):
            details["salary"] = " ".join(salary.split())
        cities = (self.get_location(element) or "").lower()
        if cities:
            details["work_format"] = "remote" if "віддалено" in cities else "office"
        # No "за кордоном" is not a refusal: companies forget the tick. The filter warns instead.
        if "за кордоном" in cities:
            details["countries"] = "за кордоном"
        return details

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
        month = _MONTHS[month_word]
        return datetime(resolve_year(month), month, int(day))

    def get_link(self, element: Tag) -> str:
        el = element.select_one(self.link)
        if not el:
            raise ValueError("No link found in Dou job")
        # Hot vacancies link with "?from=list_hot" — the same page as the plain one.
        return str(el.get("href")).split("?")[0]
