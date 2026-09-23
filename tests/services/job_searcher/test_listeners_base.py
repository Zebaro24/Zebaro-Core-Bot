from datetime import datetime
from unittest.mock import patch

import pytest

from src.services.job_searcher.listeners.base import resolve_year


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 15)


@pytest.mark.parametrize(
    "month,expected_year",
    [
        (3, 2026),  # тот же месяц, что и сейчас
        (2, 2026),  # прошедший месяц этого года
        (1, 2026),  # прошедший месяц этого года
        (4, 2025),  # на 1 месяц вперёд — не может быть будущим, значит прошлый год
        (12, 2025),  # декабрь при "сейчас" в марте — прошлый год
    ],
)
def test_resolve_year_never_returns_future_date(month, expected_year):
    with patch("src.services.job_searcher.listeners.base.datetime", _FixedDatetime):
        assert resolve_year(month) == expected_year


def test_dou_hot_vacancy_links_to_the_plain_page():
    from bs4 import BeautifulSoup

    from src.services.job_searcher.listeners.dou import DouListeners

    href = "https://jobs.dou.ua/companies/vira-games/vacancies/374084/?from=list_hot"
    element = BeautifulSoup(f'<li><a class="vt" href="{href}">Python</a></li>', "html.parser")

    listeners = DouListeners()
    assert listeners.get_link(element) == "https://jobs.dou.ua/companies/vira-games/vacancies/374084/"
    assert listeners.get_job_id(element) == "374084"


@pytest.mark.parametrize(
    "attrs,expected",
    [
        ('data-bs-original-title="23:24 22.09.2026"', datetime(2026, 9, 22, 23, 24)),
        ('title="23:24 22.09.2026"', datetime(2026, 9, 22, 23, 24)),  # before Bootstrap ran
        ("", None),
        ('title="вчора"', None),
    ],
)
def test_djinni_date_survives_a_page_captured_before_its_scripts(attrs, expected):
    from bs4 import BeautifulSoup

    from src.services.job_searcher.listeners.djinni import DjinniListeners

    element = BeautifulSoup(
        f'<div class="job-item"><span class="text-nowrap" data-bs-toggle="tooltip" {attrs}>1d</span></div>',
        "html.parser",
    )
    assert DjinniListeners().get_date(element) == expected
