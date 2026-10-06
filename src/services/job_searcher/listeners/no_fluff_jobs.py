import re

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners

_BADGE = re.compile(r"(НОВОЕ|НОВЕ|NEW|НОВАЯ)$")


class NoFluffJobsListeners(BaseListeners):
    platform_name = "No Fluff Jobs"
    all_jobs = "div.list-container > a"

    job_id = "pass"
    title = "h3"
    company = "h4"
    description = "pass"
    date = "pass"
    link = "pass"

    detail_description = "#posting-requirements, #posting-description, #posting-tasks"
    detail_noise = ("Оригинальный текст", "Показать оригинал", "Оригінальний текст", "Показати оригінал")

    def get_title(self, element: Tag) -> str | None:
        # The "new" badge sits inside the <h3>: "Full Stack DeveloperНОВОЕ".
        title = super().get_title(element)
        return _BADGE.sub("", title).strip() if title else None

    def get_job_id(self, element: Tag) -> str | None:
        val = element.get("id")
        return str(val) if val is not None else None

    def get_link(self, element: Tag) -> str:
        return f"https://nofluffjobs.com{str(element.get('href', ''))}"
