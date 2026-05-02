from datetime import datetime

from bs4.element import Tag


class BaseListeners:
    platform_name: str | None = None
    all_jobs: str | None = None

    job_id: str | None = None
    title: str | None = None
    company: str | None = None
    description: str | None = None
    date: str | None = None
    link: str | None = None

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
