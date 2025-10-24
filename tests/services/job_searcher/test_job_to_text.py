from datetime import datetime

import pytest

from app.services.job_searcher.job_container import Job
from app.services.job_searcher.job_to_text import job_to_html


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
            ["Description:", "<blockquote>Line1", "Line2</blockquote>"],
        ),
        (
            Job(title=None, platform_name=None, link=None, company=None, description="<b>bold</b>"),
            ['<a href=""> - </a>', "Company: <b></b>", "<blockquote>&lt;b&gt;bold&lt;/b&gt;</blockquote>"],
        ),
    ],
)
def test_job_to_html(job, expected_substrings):
    html_text = job_to_html(job)
    for substring in expected_substrings:
        assert substring in html_text
