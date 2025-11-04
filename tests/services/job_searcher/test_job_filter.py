import pytest

from app.services.job_searcher.job_container import Job, JobStorage
from app.services.job_searcher.job_filter import JobFilter


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Senior Python Dev", True),
        ("Junior Python Dev", False),
        ("Middle Python Dev", True),
        ("Python Dev", False),
        (None, False),
    ],
)
def test_filter_seniors(title, expected):
    job = Job(title=title)
    assert JobFilter.filter_seniors(job) is expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Python Dev", False),
        ("Full Stack Dev", False),
        ("Java Developer", True),
        (None, False),
    ],
)
def test_filter_with_title(title, expected):
    job = Job(title=title)
    assert JobFilter.filter_with_title(job) is expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Odoo Developer", True),
        ("Викладач Python", True),
        ("Python Developer", False),
        (None, False),
    ],
)
def test_filter_without_title(title, expected):
    job = Job(title=title)
    assert JobFilter.filter_without_title(job) is expected


@pytest.mark.parametrize(
    "company,expected",
    [
        ("ФОП Иванов", True),
        ("School ABC", True),
        ("TechCorp", False),
        (None, False),
    ],
)
def test_filter_without_company(company, expected):
    job = Job(company=company)
    assert JobFilter.filter_without_company(job) is expected


def test_filter_all():
    storage = JobStorage()
    jobs = [
        Job(title="Senior Python Dev", company="TechCorp"),
        Job(title="Python Developer", company="TechCorp"),
        Job(title="Full Stack Engineer", company="TechCorp"),
        Job(title="Python Lead Dev", company="TechCorp"),
        Job(title="Python Developer", company="School XYZ"),
        Job(title="Odoo Developer", company="TechCorp"),
        Job(title=None, company="TechCorp"),
        Job(title="Junior Python Dev", company="TechCorp"),
    ]
    for job in jobs:
        storage.add_job(job)

    jf = JobFilter(storage)
    jf.filter_all()

    titles_remaining = [job.title for job in storage.jobs]

    assert "Python Developer" in titles_remaining
    assert "Full Stack Engineer" in titles_remaining
    assert "Junior Python Dev" in titles_remaining

    assert "Senior Python Dev" not in titles_remaining
    assert "Python Lead Dev" not in titles_remaining
    assert "Odoo Developer" not in titles_remaining
    assert not any(job.company == "School XYZ" for job in storage.jobs)
