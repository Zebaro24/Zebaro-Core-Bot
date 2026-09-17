from datetime import datetime

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners


class BazaITListeners(BaseListeners):
    platform_name = "BazaIT"
    all_jobs = "a.company-job"

    job_id = "pass"
    title = ".company-job__main .flex.flex-col.text-sm span"
    company = "span.w-full"
    description = "pass"  # не показывается в списке, только на странице вакансии
    date = ".company-job__date"
    link = "pass"

    detail_description = ".info-item"

    def get_job_id(self, element: Tag) -> str | None:
        href = element.get("href")
        if not href:
            return None
        return str(href).rstrip("/").split("/")[-1]

    def get_date(self, element: Tag) -> datetime | None:
        date_el = element.select_one(self.date)
        if not date_el:
            return None
        date_str = date_el.get_text(strip=True)
        try:
            return datetime.strptime(date_str, "%d.%m.%Y")
        except ValueError:
            return None

    def get_link(self, element: Tag) -> str | None:
        href = element.get("href")
        return f"https://app.bazait.com{href}" if href else None
