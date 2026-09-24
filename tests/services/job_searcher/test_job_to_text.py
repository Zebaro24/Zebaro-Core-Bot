from datetime import datetime

import pytest

from src.interfaces.tg.formatters.job import job_to_html
from src.services.job_searcher.container import Job


@pytest.mark.parametrize(
    "job,expected_substrings",
    [
        (
            Job(title="Python Dev", platform_name="TestPlatform", link="https://test.com", company="TestCo"),
            ["Python Dev - TestPlatform", "Company: <b>TestCo</b>"],
        ),
        (
            Job(
                title="Python Dev",
                platform_name="TestPlatform",
                link="https://test.com",
                company="TestCo",
                date=datetime(2025, 10, 24),
            ),
            ["Date: <i>24.10.2025</i>"],
        ),
        (
            Job(
                title="Python Dev",
                platform_name="TestPlatform",
                link="https://test.com",
                company="TestCo",
                description="Line1\nLine2",
            ),
            ["Description:", "<blockquote expandable>Line1", "Line2</blockquote>"],
        ),
        (
            Job(title=None, platform_name=None, link=None, company=None, description="<b>bold</b>"),
            [" - \n", "Company: <b></b>", "<blockquote expandable>&lt;b&gt;bold&lt;/b&gt;</blockquote>"],
        ),
        (
            Job(title="AI Engineer", platform_name="Djinni", company="TestCo", moderation="sent"),
            ["🔥 AI Engineer - Djinni"],
        ),
        (
            Job(title="AI Engineer", platform_name="Djinni", company="TestCo", moderation="review"),
            ["👀 AI Engineer - Djinni"],
        ),
    ],
)
def test_job_to_html(job, expected_substrings):
    html_text = job_to_html(job)
    for substring in expected_substrings:
        assert substring in html_text


def test_job_to_html_no_link_in_title():
    job = Job(title="Python Dev", platform_name="TestPlatform", link="https://test.com", company="TestCo")
    html_text = job_to_html(job)
    assert "<a href=" not in html_text


def test_job_to_html_similar_to_shows_platform_when_hint_is_set():
    job = Job(title="Python Dev", platform_name="TestPlatform", company="TestCo", similar_to="507f1f77bcf86cd799439011")
    job.similar_to_platform = "Work.ua"

    html_text = job_to_html(job)

    assert "🔁 Похоже, уже было на Work.ua" in html_text


def test_job_to_html_similar_to_without_platform_hint_is_silent():
    job = Job(title="Python Dev", platform_name="TestPlatform", company="TestCo", similar_to="507f1f77bcf86cd799439011")

    html_text = job_to_html(job)

    assert "Похоже, уже видел" not in html_text


def test_job_to_html_says_why_in_plain_lines():
    job = Job(
        title="Middle Full Stack Developer",
        platform_name="Dou",
        company="Acme",
        moderation="sent",
        matched_stack=["Python", "React"],
        matched_bonus=["Docker"],
        required_years=2,
    )
    html_text = job_to_html(job)
    assert "\n🔥 <b>Бэк + фронт</b> — Python · React\n➕ Docker\n🎓 от 2 лет · Middle" in html_text
