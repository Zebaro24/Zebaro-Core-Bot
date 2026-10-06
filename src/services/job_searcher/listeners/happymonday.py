from datetime import datetime

from bs4 import Tag

from src.services.job_searcher import extract
from src.services.job_searcher.listeners.base import BaseListeners


class HappyMondayListeners(BaseListeners):
    platform_name = "HappyMonday"
    via_home = True
    all_jobs = "div.job_card"

    job_id = "pass"
    title = ".job_card__title a"
    company = ".job_card_company span"
    # Cards of vacancies HappyMonday copies from other sites put the company name straight into
    # the block, without the span — half of the stored ones came without a company.
    company_block = ".job_card_company"
    description = "pass"  # не показывается в списке, только на странице вакансии
    date = ".job_timing"
    link = ".job_card__title a"

    detail_description = ".single-vacancy__text"
    detail_noise = ("увійдіть або зареєструйтесь", "Бажаєте податися", "Хочете податися")

    def get_job_id(self, element: Tag) -> str | None:
        val = element.get("data-post-id")
        return str(val) if val is not None else None

    def get_company(self, element: Tag) -> str | None:
        company = super().get_company(element) or self._get_one_by_selector(element, self.company_block)
        if company:
            return company
        # "Senior Full Stack Typescript Engineer (AI) at Kind" — the title names it.
        title = self.get_title(element) or ""
        return title.rsplit(" at ", 1)[1].strip() if " at " in title else None

    def get_date(self, element: Tag) -> datetime | None:
        date_el = element.select_one(self.date)
        if not date_el:
            return None
        return extract.relative_date(date_el.get_text(strip=True).replace("Останнє оновлення", ""))

    def get_link(self, element: Tag) -> str | None:
        el = element.select_one(self.link)
        if not el:
            return None
        return f"https://happymonday.ua{el.get('href', '')}"
