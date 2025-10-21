from bs4 import Tag

from app.services.job_searcher.listeners.base_listeners import BaseListeners


class RobotaUAListeners(BaseListeners):
    platform_name = "Robota.ua"
    all_jobs = "alliance-vacancy-card-desktop"

    job_id = "a"
    title = "h2"
    company = "span.santa-mr-20"
    description = "pass"
    date = "div.santa-typo-secondary.santa-text-black-500"
    link = "a"

    def get_job_id(self, element):
        selector = element.select_one(self.job_id)
        if not selector:
            raise Exception("No job id found")
        return selector.get("href").split("/")[-1][7:]

    def get_link(self, element: Tag):
        selector = element.select_one(self.link)
        if not selector:
            raise Exception("No link found")
        return f"https://www.robota.ua{selector.get('href')}"
