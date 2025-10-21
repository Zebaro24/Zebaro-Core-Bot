from datetime import datetime

from bs4 import Tag

from app.services.job_searcher.listeners.base_listeners import BaseListeners

months = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}


class JoobleListeners(BaseListeners):
    platform_name = "Jooble"
    all_jobs = 'div.infinite-scroll-component > div > ul > li > div[data-test-name="_jobCard"]'

    job_id = "pass"
    title = "h2"
    company = 'p[data-test-name="_companyName"]'
    description = "div:nth-child(2) > div > div"
    date = "div:nth-child(2) > div > div"
    link = "a"

    def get_job_id(self, element):
        return element.get("id")

    def get_description(self, element: Tag):
        text = super().get_description(element)
        text = text.replace("\n", "")
        text = text.replace("  ", " ")
        if text.find("віддалено") != -1:
            return text.split("віддалено")[1].strip()
        return text

    def get_date(self, element: Tag):
        text = super().get_date(element)
        if not text[0].isdigit():
            return None

        date_str = text.split("2025")[0].strip() + " 2025"
        day, month_word, year = date_str.split()
        month = months[month_word]
        dt = datetime(int(year), month, int(day))
        return dt

    def get_link(self, element: Tag):
        element = element.select_one(self.link)
        if not element:
            raise Exception("No link found")
        return element.get("href")
