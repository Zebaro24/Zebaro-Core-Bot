import re
from datetime import datetime, timedelta

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners


def _parse_relative_date(text: str) -> datetime | None:
    match = re.search(r"(\d+)\s+(\w+)\s+ago", text.lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    now = datetime.now()
    if unit.startswith("hour"):
        return now - timedelta(hours=amount)
    if unit.startswith("day"):
        return now - timedelta(days=amount)
    if unit.startswith("week"):
        return now - timedelta(weeks=amount)
    if unit.startswith("month"):
        return now - timedelta(days=amount * 30)
    if unit.startswith("year"):
        return now - timedelta(days=amount * 365)
    return None


class WellfoundListeners(BaseListeners):
    platform_name = "Wellfound"
    # Каждая карточка компании может содержать несколько вакансий — итерируем по строкам вакансий,
    # а не по карточкам компаний, поэтому имя компании достаём через find_parent в get_company.
    all_jobs = "div.items-end.justify-between"

    job_id = "pass"
    title = 'a[href^="/jobs/"]'
    company = "pass"
    description = "pass"  # not in the list
    date = "span.text-xs.lowercase.text-dark-a"
    link = 'a[href^="/jobs/"]'

    # The vacancy page shows the whole description without a login (checked 17.09.2026).
    detail_description = "#job-description"

    def get_job_id(self, element: Tag) -> str | None:
        el = element.select_one(self.title)
        if not el:
            return None
        slug = str(el.get("href", "")).rstrip("/").split("/")[-1]
        return slug.split("-")[0] or None

    def get_company(self, element: Tag) -> str | None:
        card = element.find_parent("div", class_="mb-6")
        if not card:
            return None
        h2 = card.select_one("h2")
        return h2.get_text(strip=True) if h2 else None

    def get_date(self, element: Tag) -> datetime | None:
        date_el = element.select_one(self.date)
        if not date_el:
            return None
        return _parse_relative_date(date_el.get_text(strip=True))

    def get_link(self, element: Tag) -> str | None:
        el = element.select_one(self.link)
        if not el:
            return None
        href = el.get("href")
        return f"https://wellfound.com{href}" if href else None
