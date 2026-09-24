import re
from datetime import datetime, timedelta

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners


def _parse_relative_date(text: str) -> datetime | None:
    match = re.search(r"(\d+)\s+(\S+)\s+тому", text)
    if not match:
        return None
    amount = int(match.group(1))
    unit_word = match.group(2)
    now = datetime.now()
    if unit_word.startswith("хвилин"):
        return now - timedelta(minutes=amount)
    if unit_word.startswith("годин"):
        return now - timedelta(hours=amount)
    if unit_word.startswith("тижд"):
        return now - timedelta(weeks=amount)
    if unit_word.startswith("місяц"):
        return now - timedelta(days=amount * 30)
    if unit_word.startswith("д"):  # день / дні / днів
        return now - timedelta(days=amount)
    return None


class HappyMondayListeners(BaseListeners):
    platform_name = "HappyMonday"
    via_home = True
    all_jobs = "div.job_card"

    job_id = "pass"
    title = ".job_card__title a"
    company = ".job_card_company span"
    description = "pass"  # не показывается в списке, только на странице вакансии
    date = ".job_timing"
    link = ".job_card__title a"

    detail_description = ".single-vacancy__text"
    detail_noise = ("увійдіть або зареєструйтесь", "Бажаєте податися", "Хочете податися")

    def get_job_id(self, element: Tag) -> str | None:
        val = element.get("data-post-id")
        return str(val) if val is not None else None

    def get_date(self, element: Tag) -> datetime | None:
        date_el = element.select_one(self.date)
        if not date_el:
            return None
        text = date_el.get_text(strip=True).replace("Останнє оновлення", "").strip()
        return _parse_relative_date(text)

    def get_link(self, element: Tag) -> str | None:
        el = element.select_one(self.link)
        if not el:
            return None
        return f"https://happymonday.ua{el.get('href', '')}"
