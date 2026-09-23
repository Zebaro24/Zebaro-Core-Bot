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

    def get_date(self, element: Tag) -> datetime | None:
        select_element = element.select_one(self.date)
        if not select_element:
            return None
        # Bootstrap moves "title" to "data-bs-original-title" when it sets the tooltip up; a page
        # captured before its scripts ran still has the plain attribute. A missing date only
        # costs the staleness check, so it is not worth losing the vacancy over.
        date_str = select_element.get("data-bs-original-title") or select_element.get("title")
        if not isinstance(date_str, str):
            return None
        try:
            return datetime.strptime(date_str.strip(), "%H:%M %d.%m.%Y")
        except ValueError:
            return None

    def get_link(self, element: Tag) -> str:
        select_element = element.select_one(self.link)
        if not select_element:
            raise ValueError("No link found in Djinni job")
        return f"https://djinni.co{select_element.get('href')}"
