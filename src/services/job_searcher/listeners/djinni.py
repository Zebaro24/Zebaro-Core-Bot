from datetime import datetime

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners
from src.services.job_searcher.text import element_text


class DjinniListeners(BaseListeners):
    platform_name = "Djinni"
    all_jobs = "div.job-item"

    job_id = "pass"
    title = "h2.job-item__position"
    company = "span.text-gray-800"
    # The list already carries the whole description, hidden: .js-truncated-text is the first
    # ~500 characters, .js-original-text is all of it — no need to open the vacancy page.
    description = ".js-original-text"
    truncated_description = "span.js-truncated-text"
    date = 'span.text-nowrap[data-bs-toggle="tooltip"]'
    link = "a.job_item__header-link"

    def get_job_id(self, element: Tag) -> str:
        id_attr = element.get("id")
        if not id_attr:
            raise ValueError("No job id found in Djinni element")
        return str(id_attr).split("-")[-1]

    def get_description(self, element: Tag) -> str | None:
        full = element.select_one(self.description) if self.description else None
        if full:
            return element_text(full) or None
        return self._get_one_by_selector(element, self.truncated_description)

    def get_date(self, element: Tag) -> datetime:
        select_element = element.select_one(self.date)
        if not select_element:
            raise ValueError("No date element found in Djinni job")
        date_str = select_element.get("data-bs-original-title")
        if not date_str or not isinstance(date_str, str):
            raise ValueError("No date string found in Djinni element")
        return datetime.strptime(date_str, "%H:%M %d.%m.%Y")

    def get_link(self, element: Tag) -> str:
        select_element = element.select_one(self.link)
        if not select_element:
            raise ValueError("No link found in Djinni job")
        return f"https://djinni.co{select_element.get('href')}"
