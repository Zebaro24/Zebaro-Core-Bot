import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import Page, TimeoutError, async_playwright
from playwright_stealth import Stealth

from src.config import settings
from src.services.job_searcher.container import Job, JobStorage
from src.services.job_searcher.listeners.base import BaseListeners
from src.services.job_searcher.listeners.bazait import BazaITListeners
from src.services.job_searcher.listeners.djinni import DjinniListeners
from src.services.job_searcher.listeners.dou import DouListeners
from src.services.job_searcher.listeners.happymonday import HappyMondayListeners
from src.services.job_searcher.listeners.jooble import JoobleListeners
from src.services.job_searcher.listeners.no_fluff_jobs import NoFluffJobsListeners
from src.services.job_searcher.listeners.robota_ua import RobotaUAListeners
from src.services.job_searcher.listeners.wellfound import WellfoundListeners
from src.services.job_searcher.listeners.work_ua import WorkUAListeners

logger = logging.getLogger("job_searcher.parser")

_LISTENERS: dict[str, BaseListeners] = {
    "www.work.ua": WorkUAListeners(),
    "robota.ua": RobotaUAListeners(),
    "nofluffjobs.com": NoFluffJobsListeners(),
    "ua.jooble.org": JoobleListeners(),
    "djinni.co": DjinniListeners(),
    "jobs.dou.ua": DouListeners(),
    "happymonday.ua": HappyMondayListeners(),
    "app.bazait.com": BazaITListeners(),
    "wellfound.com": WellfoundListeners(),
}

_PAGE_TIMEOUT_MS = 10_000
_RENDER_TIMEOUT_MS = 8_000
# Upper bound of vacancy pages opened in one run: the very first run after adding a source
# can see a hundred new vacancies, and each page costs a couple of seconds.
MAX_DETAIL_PAGES = 60


class JobParser:
    def __init__(self, urls: list[str], job_storage: JobStorage) -> None:
        self.urls = urls
        self.job_storage = job_storage

    @staticmethod
    async def _get_page_content(page: Page, url: str, wait_selector: str | None = None) -> str:
        try:
            await page.goto(url, wait_until="load", timeout=_PAGE_TIMEOUT_MS)
        except TimeoutError:
            logger.error("Timeout for %s — continuing with current page state", url)
        if wait_selector:
            try:
                await page.wait_for_selector(wait_selector, timeout=_RENDER_TIMEOUT_MS)
            except TimeoutError:
                logger.warning("%s did not appear on %s — nothing rendered, or the page is blocked", wait_selector, url)
        return str(await page.content())

    @staticmethod
    async def _playwright_available() -> bool:
        from src.core.service_manager import ServiceManager

        if not await ServiceManager.get_instance().check_infra_health("playwright"):
            logger.warning("Playwright unavailable, skipping")
            return False
        return True

    async def parse_urls(self) -> None:
        if not await self._playwright_available():
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

                html_content = await self._get_page_content(page, url_text, listeners.get_list_wait_selector())
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

    async def fetch_descriptions(self, jobs: list[Job]) -> None:
        """Replace list snippets with the full description from each vacancy's own page.

        The lists show a couple of lines at best (DOU, Work.ua) or nothing at all (Robota.ua,
        No Fluff Jobs, HappyMonday, BazaIT). Both the relevance score and the Telegram message
        are only as good as this text. Call it after the title filter, so pages of vacancies
        that are rejected anyway are never opened.
        """
        targets = [
            job
            for job in jobs
            if job.link
            and (listeners := self.get_listeners_by_platform(job.platform_name))
            and listeners.detail_description
        ][:MAX_DETAIL_PAGES]
        if not targets or not await self._playwright_available():
            return

        logger.info("Fetching full descriptions for %d vacancies", len(targets))
        fetched = 0
        async with async_playwright() as pw:
            browser = await pw.chromium.connect(settings.playwright_ws_endpoint)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            await Stealth().apply_stealth_async(page)

            for job in targets:
                listeners = self.get_listeners_by_platform(job.platform_name)
                if listeners is None or not job.link:
                    continue
                try:
                    html_content = await self._get_page_content(page, job.link, listeners.detail_description)
                    description = listeners.get_detail_description(BeautifulSoup(html_content, "html.parser"))
                except Exception as e:
                    # One broken page must not cost the rest of the batch its descriptions.
                    logger.warning("Could not read the vacancy page %s: %s", job.link, e)
                    continue
                if description and len(description) > len(job.description or ""):
                    job.description = description
                    fetched += 1

            await browser.close()

        logger.info("Full descriptions: %d of %d", fetched, len(targets))

    @staticmethod
    def get_listeners(netloc: str) -> BaseListeners:
        if netloc not in _LISTENERS:
            raise ValueError(f"No listeners registered for: {netloc}")
        return _LISTENERS[netloc]

    @staticmethod
    def get_listeners_by_platform(platform_name: str | None) -> BaseListeners | None:
        return next((listeners for listeners in _LISTENERS.values() if listeners.platform_name == platform_name), None)
