from datetime import datetime
from typing import Any

from bs4 import Tag

from src.services.job_searcher import extract
from src.services.job_searcher.listeners.base import BaseListeners

# Every line of a Work.ua card starts with an icon whose title says what the line is. Picking a
# line by position or by "div > span > span" took the salary's "Після всіх відрахувань" for the
# company on every card with a salary (06.10.2026).
_COMPANY = "Дані про компанію"
_SALARY = "Зарплата"
_PLACE = "Адреса роботи"
_TERMS = "Умови й вимоги"
# The filter's limit is 3 years (filter.MAX_YEARS); kept here to avoid importing the filter.
_TOO_MANY_YEARS = 4


def _line(card: Tag, title: str) -> Tag | None:
    icon = card.select_one(f'span.glyphicon[title="{title}"]')
    return icon.parent if icon and isinstance(icon.parent, Tag) else None


class WorkUAListeners(BaseListeners):
    platform_name = "Work.ua"
    via_home = True
    all_jobs = "#pjax-jobs-list > .job-link"

    job_id = "pass"
    title = "div > h2 > a"
    company = "span.strong-600"  # inside the company line
    description = "div > p"
    date = "div > time"
    link = "pass"

    detail_description = "#job-description"

    def get_job_id(self, element: Tag) -> str:
        el = element.select_one("div > h2 > a")
        if not el or not el.get("href"):
            raise ValueError("No job id found in Work.ua element")
        return str(el.get("href")).split("/")[-2]

    def get_company(self, element: Tag) -> str | None:
        line = _line(element, _COMPANY)
        name = line.select_one(self.company or "") if line else None
        return name.get_text(" ", strip=True) if name else None

    def get_details(self, element: Tag) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if (line := _line(element, _SALARY)) and (amount := line.select_one("span.strong-600")):
            details["salary"] = " ".join(amount.get_text(" ", strip=True).split())
        if line := _line(element, _PLACE):
            details["work_format"] = extract.work_format(line.get_text(" ", strip=True)) or "office"
        # "Досвід від 2 років" is a coarse floor (1, 2 or 5 years), not the requirement: the card
        # figure counts only when it already rules the vacancy out; otherwise the description says.
        terms = _line(element, _TERMS)
        years = extract.card_years(terms.get_text(" ", strip=True)) if terms else None
        if years is not None and years >= _TOO_MANY_YEARS:
            details["required_years"] = years
        return details

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
