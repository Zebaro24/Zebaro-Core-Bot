from datetime import datetime

from bs4.element import Tag

from src.services.job_searcher.text import drop_lines, element_text


def resolve_year(month: int) -> int:
    now = datetime.now()
    if month > now.month:
        return now.year - 1
    return now.year


class BaseListeners:
    platform_name: str | None = None
    all_jobs: str | None = None

    job_id: str | None = None
    title: str | None = None
    company: str | None = None
    description: str | None = None
    location: str | None = None
    date: str | None = None
    link: str | None = None

    # Waited for after the list page loads (defaults to `all_jobs`). Robota.ua and No Fluff Jobs
    # render the cards with JavaScript after the `load` event, so the page taken at `load` had
    # zero vacancies on it.
    wait_for: str | None = None
    # Full description on the vacancy's own page. Several comma-separated selectors are joined
    # in page order. None: the site shows no more than the list does (or only after a login).
    detail_description: str | None = None
    # Site chrome that sits inside the description block and must not reach the message.
    detail_noise: tuple[str, ...] = ()

    @staticmethod
    def _get_one_by_selector(element: Tag, selector_text: str) -> str | None:
        selector = element.select_one(selector_text)
        if not selector:
            return None
        return selector.get_text(strip=True)

    @staticmethod
    def _get_all_by_selector(element: Tag, selector_text: str):
        return element.select(selector_text)

    def get_all_jobs(self, element: Tag):
        if not self.all_jobs:
            return []
        return self._get_all_by_selector(element, self.all_jobs)

    def get_job_id(self, element: Tag) -> str | None:
        if not self.job_id:
            return None
        return self._get_one_by_selector(element, self.job_id)

    def get_title(self, element: Tag) -> str | None:
        if not self.title:
            return None
        return self._get_one_by_selector(element, self.title)

    def get_company(self, element: Tag) -> str | None:
        if not self.company:
            return None
        return self._get_one_by_selector(element, self.company)

    def get_description(self, element: Tag) -> str | None:
        if not self.description:
            return None
        return self._get_one_by_selector(element, self.description)

    def get_location(self, element: Tag) -> str | None:
        if not self.location:
            return None
        return self._get_one_by_selector(element, self.location)

    def get_list_wait_selector(self) -> str | None:
        return self.wait_for or self.all_jobs

    def get_detail_description(self, page: Tag) -> str | None:
        if not self.detail_description:
            return None
        parts = [element_text(el) for el in page.select(self.detail_description)]
        text = "\n\n".join(part for part in parts if part)
        if self.detail_noise:
            text = drop_lines(text, list(self.detail_noise))
        return text or None

    def get_date(self, element: Tag) -> str | datetime | None:
        if not self.date:
            return None
        return self._get_one_by_selector(element, self.date)

    def get_link(self, element: Tag) -> str | None:
        if not self.link:
            return None
        return self._get_one_by_selector(element, self.link)

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.__dict__})"
