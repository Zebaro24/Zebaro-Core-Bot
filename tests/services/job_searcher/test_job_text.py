import pytest
from bs4 import BeautifulSoup, Tag

from src.services.job_searcher.listeners.bazait import BazaITListeners
from src.services.job_searcher.listeners.djinni import DjinniListeners
from src.services.job_searcher.listeners.dou import DouListeners
from src.services.job_searcher.listeners.happymonday import HappyMondayListeners
from src.services.job_searcher.listeners.no_fluff_jobs import NoFluffJobsListeners
from src.services.job_searcher.listeners.robota_ua import RobotaUAListeners
from src.services.job_searcher.listeners.wellfound import WellfoundListeners
from src.services.job_searcher.listeners.work_ua import WorkUAListeners
from src.services.job_searcher.text import drop_lines, element_text


def _soup(markup: str) -> BeautifulSoup:
    return BeautifulSoup(markup, "html.parser")


def _first(markup: str) -> Tag:
    tag = _soup(markup).find()
    assert isinstance(tag, Tag)
    return tag


def test_element_text_keeps_structure():
    # The shape of a real DOU description: <p>, <h3>, <ul> with <strong> inside, &nbsp;.
    markup = (
        "<div><p>We&nbsp;are looking for an&nbsp;<strong>experienced</strong> developer.</p>"
        "<h3>Requirements</h3><ul><li><strong>7+</strong>&nbsp;years</li><li>Python</li></ul>"
        "<p>Line one<br>Line two</p><script>tracking()</script></div>"
    )
    text = element_text(_first(markup))

    assert text == (
        "We are looking for an experienced developer.\n\n"
        "Requirements\n\n"
        "• 7+ years\n• Python\n\n"
        "Line one\nLine two"
    )


def test_drop_lines_removes_site_chrome():
    text = "О должности\nОригинальный текст.\nПоказать оригинал\n\nWe are looking for a developer"
    assert drop_lines(text, ["Оригинальный текст", "Показать оригинал"]) == (
        "О должности\n\nWe are looking for a developer"
    )


@pytest.mark.parametrize(
    "listeners,markup,expected",
    [
        (DouListeners(), '<div class="b-typo vacancy-section"><p>Full DOU text</p></div>', "Full DOU text"),
        (WorkUAListeners(), '<div id="job-description"><p>Full Work.ua text</p></div>', "Full Work.ua text"),
        (RobotaUAListeners(), '<div id="description-wrap"><p>Full Robota text</p></div>', "Full Robota text"),
        (
            WellfoundListeners(),
            '<div id="job-description"><p>Location: Phoenix<br>Salary: $76,000</p></div>',
            "Location: Phoenix\nSalary: $76,000",
        ),
        (
            NoFluffJobsListeners(),
            '<section id="posting-requirements"><ul><li>Python</li></ul></section>'
            '<section id="posting-description">Оригинальный текст.<br>Показать оригинал<p>About</p></section>'
            '<section id="posting-tasks"><p>Tasks</p></section>',
            "• Python\n\nAbout\n\nTasks",
        ),
        (
            HappyMondayListeners(),
            '<div class="single-vacancy__text"><p>Job text</p><p>Хочете податися? Будь ласка, увійдіть або '
            "зареєструйтесь, щоб побачити деталі.</p></div>",
            "Job text",
        ),
        (
            BazaITListeners(),
            '<div class="info-item"><h4>Summary</h4><p>One</p></div><div class="info-item"><h4>Stack</h4>'
            "<p>Two</p></div>",
            "Summary\n\nOne\n\nStack\n\nTwo",
        ),
    ],
)
def test_detail_description_selectors(listeners, markup, expected):
    assert listeners.get_detail_description(_soup(f"<html><body>{markup}</body></html>")) == expected


def test_detail_description_absent_when_the_page_does_not_have_it():
    assert DouListeners().get_detail_description(_soup("<html><body>blocked</body></html>")) is None


def test_djinni_takes_the_full_hidden_description_from_the_list():
    card = _first(
        '<div class="job-item"><span class="js-truncated-text">Short…</span>'
        '<span class="js-original-text d-none"><p><strong>What we build</strong><br>Everything</p></span></div>'
    )
    assert DjinniListeners().get_description(card) == "What we build\nEverything"


def test_djinni_falls_back_to_the_truncated_text():
    card = _first('<div class="job-item"><span class="js-truncated-text">Short text</span></div>')
    assert DjinniListeners().get_description(card) == "Short text"


def test_list_waits_for_the_cards_by_default():
    assert RobotaUAListeners().get_list_wait_selector() == "alliance-vacancy-card-desktop"
