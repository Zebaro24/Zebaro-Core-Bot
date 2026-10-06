"""What the boards show apart from the text: Djinni's card, DOU's cities, the fixed fields."""

from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from src.services.job_searcher.listeners.djinni import DjinniListeners
from src.services.job_searcher.listeners.dou import DouListeners
from src.services.job_searcher.listeners.happymonday import HappyMondayListeners
from src.services.job_searcher.listeners.no_fluff_jobs import NoFluffJobsListeners
from src.services.job_searcher.listeners.robota_ua import RobotaUAListeners
from src.services.job_searcher.listeners.work_ua import WorkUAListeners
from src.services.job_searcher.parser import JobParser

# A Djinni card as the list renders it (06.10.2026), the description left out.
DJINNI_CARD = """
<div class="job-item" id="job-item-764691">
  <a class="job_item__header-link" href="/jobs/764691-junior-python-software-engineer/">
    <header>
      <h2 class="job-item__position">Junior Python Software Engineer</h2>
      <span class="small text-gray-800">Keymakr</span>
      <strong class="text-success"><span>до&nbsp;$700</span></strong>
    </header>
  </a>
  <div class="fw-medium d-flex flex-wrap">
    <span class="text-nowrap">Тільки віддалено</span><span class="middot">·</span>
    <span><span class="location-text">Країни Європи та Україна</span></span><span class="middot">·</span>
    <span class="text-nowrap">2 роки досвіду</span><span class="middot">·</span>
    <span class="text-nowrap">Англійська - B2</span><span class="middot">·</span>
    <span class="text-nowrap">Machine Learning / Big Data</span>
  </div>
  <div class="d-flex flex-column gap-1">
    <div class="d-flex align-items-center gap-1 fs-5">
      <span class="text-nowrap">1878 переглядів</span>
      <span class="text-nowrap">227 відгуків</span>
      <span class="text-nowrap" data-bs-toggle="tooltip" title="12:01 06.10.2026">34хв</span>
    </div>
  </div>
</div>
"""

DOU_CARD = """
<li class="l-vacancy">
  <div class="date">8 вересня</div>
  <div class="title">
    <a class="vt" href="https://jobs.dou.ua/companies/fuib/vacancies/367416/?from=list_hot">Agentic AI Engineer</a>
    <strong>в <a class="company" href="#">ПУМБ</a></strong>
    <span class="salary">$3500–4500</span>
    <span class="cities">{cities}</span>
  </div>
  <div class="sh-info">About the team</div>
</li>
"""


def _card(html: str, selector: str):
    return BeautifulSoup(html, "html.parser").select_one(selector)


def test_djinni_card_gives_the_fields_djinni_checks_an_application_against():
    details = DjinniListeners().get_details(_card(DJINNI_CARD, "div.job-item"))

    assert details == {
        "work_format": "remote",
        "countries": "Країни Європи та Україна",
        "required_years": 2,
        "english": "B2",
        "salary": "до $700",
        "applicants": 227,
    }


def test_djinni_card_fields_reach_the_job():
    soup = BeautifulSoup(f'<div id="list">{DJINNI_CARD}</div>', "html.parser")

    [job] = JobParser._parse_list(DjinniListeners(), soup, "https://djinni.co/jobs/keyword-python/")

    assert job.english == "B2" and job.countries == "Країни Європи та Україна"
    assert job.search_url == "https://djinni.co/jobs/keyword-python/"


def test_dou_cities_say_remote_and_whether_abroad_is_fine():
    abroad = DouListeners().get_details(_card(DOU_CARD.format(cities="за кордоном, віддалено"), "li"))
    home = DouListeners().get_details(_card(DOU_CARD.format(cities="Київ, віддалено"), "li"))
    office = DouListeners().get_details(_card(DOU_CARD.format(cities="Львів"), "li"))

    assert abroad == {"salary": "$3500–4500", "work_format": "remote", "countries": "за кордоном"}
    assert "countries" not in home  # no tick is not a refusal — the filter only warns
    assert office["work_format"] == "office"


def test_robota_ua_relative_date_becomes_a_date():
    card = _card('<div><div class="santa-typo-secondary santa-text-black-500">2 дні тому</div></div>', "div")

    date = RobotaUAListeners().get_date(card)

    assert isinstance(date, datetime)
    assert abs((datetime.now() - timedelta(days=2) - date).total_seconds()) < 60


def test_happymonday_company_falls_back_to_the_block_and_the_title():
    block = _card('<div class="job_card"><div class="job_card_company">Acme</div></div>', "div.job_card")
    titled = _card(
        '<div class="job_card"><div class="job_card__title"><a href="/jobs/1">Senior Engineer at Kind</a></div></div>',
        "div.job_card",
    )

    assert HappyMondayListeners().get_company(block) == "Acme"
    assert HappyMondayListeners().get_company(titled) == "Kind"


def test_no_fluff_jobs_title_loses_the_new_badge():
    card = _card('<a id="1" href="/job/x"><h3>Full Stack DeveloperНОВОЕ</h3></a>', "a")

    assert NoFluffJobsListeners().get_title(card) == "Full Stack Developer"


WORK_UA_CARD = """
<div class="card job-link">
  <div><h2 class="my-0"><a href="/jobs/7428097/">Junior Full-stack Developer (React, Node.js)</a></h2></div>
  <div><div class="text-indent">
    <span class="glyphicon" title="Зарплата"></span><span class="strong-600">30 000 – 70 000 грн</span>
    <span class="text-default-7">·</span>
    <span class="js-salary-deduction"><span class="glyphicon" title="Зарплата після всіх відрахувань"></span>
      <span class="strong-600">Після всіх відрахувань</span></span>
  </div></div>
  <div class="mt-sm">
    <div class="text-indent"><span class="glyphicon" title="Дані про компанію"></span>
      <span class="mr-xs"><span class="strong-600">UncleSolutions</span></span></div>
    <div class="text-indent"><span class="glyphicon" title="Адреса роботи"></span><span>Дистанційно</span></div>
    <div class="text-indent"><span class="glyphicon" title="Умови й вимоги"></span>
      <span>Досвід від {years} · Стандартний графік: 5/2</span></div>
  </div>
</div>
"""


def test_work_ua_reads_each_line_by_its_icon_not_the_salary_note():
    card = _card(WORK_UA_CARD.format(years="1 року"), "div.job-link")
    listeners = WorkUAListeners()

    assert listeners.get_company(card) == "UncleSolutions"
    assert listeners.get_details(card) == {"salary": "30 000 – 70 000 грн", "work_format": "remote"}


def test_work_ua_card_years_count_only_when_they_rule_the_vacancy_out():
    card = _card(WORK_UA_CARD.format(years="5 років"), "div.job-link")

    assert WorkUAListeners().get_details(card)["required_years"] == 5


def test_robota_ua_links_go_without_www():
    card = _card('<div><a href="/company1020/vacancy10927041">x</a></div>', "div")

    assert RobotaUAListeners().get_link(card) == "https://robota.ua/company1020/vacancy10927041"
