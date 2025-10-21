import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError, async_playwright
from playwright_stealth import Stealth

from app.config import settings
from app.services.job_searcher.job_container import Job, JobStorage
from app.services.job_searcher.listeners.djinni_listeners import DjinniListeners
from app.services.job_searcher.listeners.dou_listeners import DouListeners
from app.services.job_searcher.listeners.jooble_listeners import JoobleListeners
from app.services.job_searcher.listeners.no_fluff_jobs_listeners import NoFluffJobsListeners
from app.services.job_searcher.listeners.robota_ua_listeners import RobotaUAListeners
from app.services.job_searcher.listeners.work_ua_listeners import WorkUAListeners

logger = logging.getLogger("playwright.async_api")

listeners_dict = {
    "www.work.ua": WorkUAListeners(),
    "robota.ua": RobotaUAListeners(),
    "nofluffjobs.com": NoFluffJobsListeners(),
    "ua.jooble.org": JoobleListeners(),
    "djinni.co": DjinniListeners(),
    "jobs.dou.ua": DouListeners(),
    # https://www.pracuj.pl/
}


class JobParser:
    def __init__(self, urls: list[str], jos_storage: JobStorage):
        self.urls = urls
        self.jos_storage = jos_storage

    @staticmethod
    async def get_page(page, url: str):
        try:
            await page.goto(url, wait_until="load", timeout=5000)
        except TimeoutError:
            logger.error(f"Превышен таймаут для {url}, продолжаем с текущим состоянием страницы")
        return await page.content()

    async def parse_urls(self):
        async with async_playwright() as pw:
            browser = await pw.chromium.connect(settings.playwright_ws_endpoint)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            stealth = Stealth()
            await stealth.apply_stealth_async(page)

            for url_text in self.urls:
                logger.info(f"Parsing {url_text}")
                url = urlparse(url_text)
                listeners = self.get_listeners(url.netloc)

                html_content = await self.get_page(page, url_text)
                soup = BeautifulSoup(html_content, "html.parser")

                for job_elem in listeners.get_all_jobs(soup):
                    job = Job()
                    job.platform_name = listeners.platform_name
                    job.job_id = listeners.get_job_id(job_elem)
                    job.title = listeners.get_title(job_elem)
                    job.company = listeners.get_company(job_elem)
                    job.description = listeners.get_description(job_elem)
                    job.date = listeners.get_date(job_elem)
                    job.link = listeners.get_link(job_elem)

                    self.jos_storage.add_job(job)

            await browser.close()

    @staticmethod
    def get_listeners(netloc):
        if netloc not in listeners_dict:
            raise ValueError(f"No listeners for {netloc}")
        return listeners_dict[netloc]


if __name__ == "__main__":
    test_urls = [
        "https://www.work.ua/jobs-remote-python+developer/",
        # "https://robota.ua/zapros/python-developer/ukraine/params;scheduleIds=3",
        # "https://robota.ua/zapros/python-developer/other_countries/params;scheduleIds=3",
        # "https://nofluffjobs.com/ua-ru/viddalena-robota?criteria=jobPosition%3D%27python%20developer%27",
        # "https://ua.jooble.org/SearchResult?date=3&rgns=Віддалено&ukw=python%20developer",
        # "https://ua.jooble.org/SearchResult?date=2&loc=2&ukw=python%20developer",
        # "https://djinni.co/jobs/?all_keywords=Python&title_only=on&employment=remote",
        # "https://jobs.dou.ua/vacancies/?remote&category=Python",
        # "https://jobs.dou.ua/vacancies/?relocation&category=Python",
    ]
    job_storage = JobStorage()
    parser = JobParser(test_urls, job_storage)
    parser.parse_urls()
