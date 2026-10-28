import re
from datetime import datetime
from typing import Any

from bs4 import Tag

from src.services.job_searcher.listeners.base import BaseListeners

_JOB_ID = re.compile(r"jobPosting:(\d+)")
_LINK_ID = re.compile(r"/jobs/view/(?:[^/?]*-)?(\d+)")


class LinkedInListeners(BaseListeners):
    """LinkedIn's guest job search: the fragment the public search page loads more cards from.

    No login, but LinkedIn answers 429 after a few dozen requests from one address (checked
    28.10.2026), so the searches are few, one page each, and go out through the home PC.
    """

    platform_name = "LinkedIn"
    via_home = True
    # A <div> with a link inside, or the whole card as an <a> — both carry the class.
    all_jobs = ".base-search-card"

    title = "h3.base-search-card__title"
    company = "h4.base-search-card__subtitle"
    location = "span.job-search-card__location"
    date = "time"
    link = "a.base-card__full-link"

    # The guest posting fragment: the full text and "Seniority level · Employment type". The
    # vacancy page itself answers a browser without a login with HTTP 999.
    detail_description = ".show-more-less-html__markup"
    # Each posting is one more request towards the 429: a run after the home PC was off would
    # spend the limit on descriptions and leave the rest with none.
    max_detail_pages = 15

    def get_job_id(self, element: Tag) -> str:
        match = _JOB_ID.search(str(element.get("data-entity-urn", "")))
        if not match:
            raise ValueError("No job id found in LinkedIn element")
        return match.group(1)

    def get_location(self, element: Tag) -> str | None:
        # Every search asks for remote work only (f_WT=2), and the card names just where the
        # company is: "Ukraine", "Lviv, Lviv, Ukraine". Without the word the filter took it for
        # an office.
        place = super().get_location(element)
        return f"{place}, remote" if place else "remote"

    def get_details(self, element: Tag) -> dict[str, Any]:
        return {"work_format": "remote"}

    def get_date(self, element: Tag) -> datetime | None:
        el = element.select_one(self.date or "")
        raw = el.get("datetime") if el else None
        if not isinstance(raw, str):
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None

    def get_link(self, element: Tag) -> str:
        # "https://ua.linkedin.com/jobs/view/middle-python-...-4481863287?position=1&refId=…":
        # the tracking query and the country subdomain go, the id stays.
        return f"https://www.linkedin.com/jobs/view/{self.get_job_id(element)}/"

    def detail_url(self, link: str) -> str:
        match = _LINK_ID.search(link)
        if not match:
            return link
        return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{match.group(1)}"
