import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError, async_playwright
from playwright_stealth import Stealth

from src.config import settings
from src.services.job_searcher.container import Job, JobStorage
from src.services.job_searcher.listeners.djinni import DjinniListeners
from src.services.job_searcher.listeners.dou import DouListeners
from src.services.job_searcher.listeners.jooble import JoobleListeners
from src.services.job_searcher.listeners.no_fluff_jobs import NoFluffJobsListeners
from src.services.job_searcher.listeners.robota_ua import RobotaUAListeners
from src.services.job_searcher.listeners.work_ua import WorkUAListeners

logger = logging.getLogger("job_searcher.parser")

_LISTENERS = {
    "www.work.ua": WorkUAListeners(),
    "robota.ua": RobotaUAListeners(),
    "nofluffjobs.com": NoFluffJobsListeners(),
    "ua.jooble.org": JoobleListeners(),
    "djinni.co": DjinniListeners(),
    "jobs.dou.ua": DouListeners(),
}


class JobParser:
    def __init__(self, urls: list[str], job_storage: JobStorage) -> None:
        self.urls = urls
        self.job_storage = job_storage

    @staticmethod
    async def _get_page_content(page, url: str) -> str:
        try:
            await page.goto(url, wait_until="load", timeout=5000)
        except TimeoutError:
            logger.error("Timeout for %s — continuing with current page state", url)
        return str(await page.content())

    async def parse_urls(self) -> None:
        from src.core.service_manager import ServiceManager

        if not await ServiceManager.get_instance().check_infra_health("playwright"):
            logger.warning("Playwright unavailable, skipping job parse")
            return

        logger.info("Starting parse for %d URLs", len(self.urls))
        async with async_playwright() as pw:
            browser = await pw.chromium.connect(settings.playwright_ws_endpoint)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            await Stealth().apply_stealth_async(page)

            for url_text in self.urls:
                logger.info("Parsing: %s", url_text)
                netloc = urlparse(url_text).netloc
                listeners = self.get_listeners(netloc)

                html_content = await self._get_page_content(page, url_text)
                soup = BeautifulSoup(html_content, "html.parser")

                count = 0
                for job_elem in listeners.get_all_jobs(soup):
                    job = Job(
                        platform_name=listeners.platform_name,
                        job_id=listeners.get_job_id(job_elem),
                        title=listeners.get_title(job_elem),
                        company=listeners.get_company(job_elem),
                        description=listeners.get_description(job_elem),
                        date=listeners.get_date(job_elem),
                        link=listeners.get_link(job_elem),
                    )
                    self.job_storage.add_job(job)
                    count += 1

                logger.info("Found %d jobs on %s", count, netloc)

            await browser.close()

        logger.info("Parse complete. Total: %d jobs", len(self.job_storage.jobs))

    @staticmethod
    def get_listeners(netloc: str):
        if netloc not in _LISTENERS:
            raise ValueError(f"No listeners registered for: {netloc}")
        return _LISTENERS[netloc]
