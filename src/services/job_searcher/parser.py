import json
import logging
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page, TimeoutError, async_playwright
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


def platform_names() -> set[str]:
    """Names of the platforms the current searches cover, as they are stored on a Job."""
    from src.services.job_searcher.urls import urls

    names = set()
    for url in urls:
        listeners = _LISTENERS.get(urlparse(url).netloc)
        if listeners and listeners.platform_name:
            names.add(listeners.platform_name)
    return names


def _is_challenge(title: str, content: str) -> bool:
    # The title first: Cloudflare puts a long inline stylesheet before it, so on Work.ua's
    # vacancy pages "Трохи зачекайте…" sat past any fixed slice of the HTML and went unseen.
    head = f"{title}\n{content[:4000]}".lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


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
# A bot-check interstitial reloads itself after a few seconds; this is the second chance
# the list gets before the source is written off as blocked.
_CHALLENGE_WAIT_MS = 6_000
# Upper bound of vacancy pages opened in one run: the very first run after adding a source
# can see a hundred new vacancies, and each page costs a couple of seconds.
MAX_DETAIL_PAGES = 60

# Which browser the Playwright server launches for us. Its default is "chromium headless
# shell" — a stripped build that Cloudflare recognises: Work.ua, Robota.ua and HappyMonday
# answered it with a "Трохи зачекайте…" page on every run. The full Chromium in its new
# headless mode, from the same image, got through all three in a live check (23.09.2026).
_LAUNCH_OPTIONS = {"channel": "chromium", "headless": True}


def browser_endpoint() -> str:
    """The Playwright server address with the launch options it passes to the browser."""
    separator = "&" if "?" in settings.playwright_ws_endpoint else "?"
    return f"{settings.playwright_ws_endpoint}{separator}launch-options={quote(json.dumps(_LAUNCH_OPTIONS))}"


# A headless browser's own user agent says HeadlessChrome and its context has no locale or
# timezone. The Cloudflare-guarded boards look exactly at that fingerprint, so every page is
# opened from a context that looks like the browser a person in Kyiv would use.
_CONTEXT_OPTIONS = {
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    "locale": "uk-UA",
    "timezone_id": "Europe/Kyiv",
    "viewport": {"width": 1440, "height": 900},
    "extra_http_headers": {"Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6"},
}

# Text a bot check leaves on the page instead of the vacancies.
_CHALLENGE_MARKERS = (
    "just a moment",
    "трохи зачекайте",  # Cloudflare's page in Ukrainian — what Work.ua and Robota.ua show
    "один момент",
    "checking your browser",
    "challenge-platform",
    "cf-challenge",
    "enable javascript and cookies",
)


class JobParser:
    def __init__(self, urls: list[str], job_storage: JobStorage) -> None:
        self.urls = urls
        self.job_storage = job_storage

    @staticmethod
    async def _get_page_content(page: Page, url: str, wait_selector: str | None = None) -> str:
        status = None
        try:
            response = await page.goto(url, wait_until="load", timeout=_PAGE_TIMEOUT_MS)
            status = response.status if response else None
        except TimeoutError:
            logger.error("Timeout for %s — continuing with current page state", url)

        if wait_selector:
            try:
                await page.wait_for_selector(wait_selector, timeout=_RENDER_TIMEOUT_MS)
            except TimeoutError:
                # Either the site renders nothing for us, or it shows a bot check that
                # reloads itself — worth one more wait before giving the source up.
                if _is_challenge(await page.title(), await page.content()):
                    logger.warning("Bot check on %s (HTTP %s), waiting it out", url, status)
                    await page.wait_for_timeout(_CHALLENGE_WAIT_MS)
                    try:
                        await page.wait_for_selector(wait_selector, timeout=_RENDER_TIMEOUT_MS)
                    except TimeoutError:
                        logger.error("%s is blocked by a bot check (HTTP %s) — no vacancies", url, status)
                else:
                    logger.warning(
                        "%s did not appear on %s (HTTP %s, title %r) — nothing rendered",
                        wait_selector,
                        url,
                        status,
                        await page.title(),
                    )
        return str(await page.content())

    @staticmethod
    async def _new_page(browser: Browser) -> Page:
        context = await browser.new_context(**_CONTEXT_OPTIONS)  # type: ignore[arg-type]
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        return page

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
            browser = await pw.chromium.connect(browser_endpoint())
            page = await self._new_page(browser)

            for url_text in self.urls:
                logger.info("Parsing: %s", url_text)
                netloc = urlparse(url_text).netloc
                listeners = self.get_listeners(netloc)
                try:
                    html_content = await self._get_page_content(page, url_text, listeners.get_list_wait_selector())
                except Exception:
                    # A page that fails to load must not cost every other source its vacancies.
                    logger.exception("Could not open %s, moving on to the next search", url_text)
                    continue

                jobs = self._parse_list(listeners, BeautifulSoup(html_content, "html.parser"))
                repeated = sum(not self.job_storage.add_job(job) for job in jobs)

                if jobs:
                    logger.info("Found %d jobs on %s (%d already found by another search)", len(jobs), netloc, repeated)
                else:
                    # A source that suddenly gives nothing is a broken selector or a block,
                    # and silence in the logs is how it stayed unnoticed for weeks.
                    logger.warning("Found 0 jobs on %s (page title %r)", netloc, await self._title(page))

            await browser.close()

        logger.info("Parse complete. Total: %d jobs", len(self.job_storage.jobs))

    @staticmethod
    async def _title(page: Page) -> str | None:
        # Only for the log line: a page mid-navigation or crashed must not end the run.
        try:
            return await page.title()
        except Exception:
            return None

    @staticmethod
    def _parse_list(listeners: BaseListeners, soup: BeautifulSoup) -> list[Job]:
        jobs = []
        for job_elem in listeners.get_all_jobs(soup):
            try:
                jobs.append(
                    Job(
                        platform_name=listeners.platform_name,
                        job_id=listeners.get_job_id(job_elem),
                        title=listeners.get_title(job_elem),
                        company=listeners.get_company(job_elem),
                        description=listeners.get_description(job_elem),
                        location=listeners.get_location(job_elem),
                        date=listeners.get_date(job_elem),
                        link=listeners.get_link(job_elem),
                    )
                )
            except Exception as e:
                # One odd card (an ad, a half-rendered tooltip) used to raise out of the whole
                # run — and then no vacancy from any site arrived.
                logger.warning("Skipped a %s card that did not parse: %s", listeners.platform_name, e)
        return jobs

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
        # Work.ua lets the list through but guards every vacancy page with a check no headless
        # browser passes (checked 23.09.2026). Each blocked page costs ~20 s of waiting, so
        # after the first one the rest of that site keeps its list snippet.
        blocked: set[str | None] = set()
        async with async_playwright() as pw:
            browser = await pw.chromium.connect(browser_endpoint())
            page = await self._new_page(browser)

            for job in targets:
                listeners = self.get_listeners_by_platform(job.platform_name)
                if listeners is None or not job.link or job.platform_name in blocked:
                    continue
                try:
                    html_content = await self._get_page_content(page, job.link, listeners.detail_description)
                    description = listeners.get_detail_description(BeautifulSoup(html_content, "html.parser"))
                    if not description and _is_challenge(await page.title(), html_content):
                        blocked.add(job.platform_name)
                        logger.warning(
                            "%s vacancy pages are behind a bot check — its vacancies keep the list snippet",
                            job.platform_name,
                        )
                        continue
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
