from datetime import datetime

from bs4 import Tag

from src.services.job_searcher import extract
from src.services.job_searcher.listeners.base import BaseListeners

ROBOTA_UA = "https://robota.ua"


class RobotaUAListeners(BaseListeners):
    platform_name = "Robota.ua"
    via_home = True
    all_jobs = "alliance-vacancy-card-desktop"

    job_id = "a"
    title = "h2"
    company = "span.santa-mr-20"
    description = "pass"
    date = "div.santa-typo-secondary.santa-text-black-500"
    link = "a"

    detail_description = "#description-wrap"

    def get_job_id(self, element: Tag) -> str:
        el = element.select_one(self.job_id)
        if not el:
            raise ValueError("No job id found in Robota.ua element")
        return str(el.get("href")).split("/")[-1][7:]

    def get_date(self, element: Tag) -> datetime | None:
        # "2 дні тому", "19 годин тому" — stored as text, it broke the staleness check and the
        # date in the message (06.10.2026).
        raw = super().get_date(element)
        return extract.relative_date(raw) if isinstance(raw, str) else None

    def get_link(self, element: Tag) -> str:
        el = element.select_one(self.link)
        if not el:
            raise ValueError("No link found in Robota.ua element")
        # No "www": www.robota.ua answers 404 for every vacancy page (06.10.2026) — the button led
        # nowhere and the description never loaded.
        return f"{ROBOTA_UA}{el.get('href')}"
