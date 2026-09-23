from datetime import datetime, timedelta

import pytest

from src.services.job_searcher.container import Job, JobStorage
from src.services.job_searcher.filter import (
    MAX_AGE_DAYS,
    JobFilter,
    evaluate,
    required_years,
    title_reject_reason,
)


@pytest.mark.parametrize(
    "title,company,reason",
    [
        ("Senior Python Developer", "TechCorp", "senior"),
        ("Sr. Full Stack Engineer (Python / React)", "TechCorp", "senior"),
        ("Senior AI Engineer", "TechCorp", "senior"),  # AI no longer rescues a senior title
        ("Team Lead Python", "TechCorp", "lead"),
        ("Lead Python Developer (Database)", "Nova Digital", "lead"),
        ("Head of Engineering", "TechCorp", "lead"),
        ("Solution Architect", "TechCorp", "lead"),
        ("Trainee Frontend (React)", "TechCorp", "intern"),
        ("Python Intern", "TechCorp", "intern"),
        ("Стажування Python-розробник", "TechCorp", "intern"),
        ("QA Engineer Python", "TechCorp", "not a developer role"),
        ("AI Training Data Labeling", "TechCorp", "not a developer role"),
        ("Product Manager", "TechCorp", "not a developer role"),
        ("Python Developer", "ФОП Іванов", "company"),
        ("Python Developer", "School ABC", "company"),
    ],
)
def test_title_rejects(title, company, reason):
    assert title_reject_reason(title, company) == reason
    verdict = evaluate(Job(title=title, company=company, description="Python FastAPI React Next.js"))
    assert verdict.moderation == "rejected_by_filter"
    assert verdict.reason == reason


@pytest.mark.parametrize(
    "title",
    [
        "Middle/Senior Python Developer",  # still hires a middle
        "Junior/Middle Python Developer",
        "Junior Python Developer",  # a strong junior with two years of work is the owner's level
        "Strong Junior Full Stack Developer",
        "Junior/Trainee React Developer",  # hires a junior too
        "Middle Python Developer",
        "Python Developer",
        "Software Engineer",
    ],
)
def test_titles_that_stay(title):
    assert title_reject_reason(title, "TechCorp") is None


@pytest.mark.parametrize(
    "title,description,moderation,stack",
    [
        # 🔥 your stack: backend core AND frontend core
        ("Full Stack Developer", "Python, FastAPI, React, Next.js", "sent", ["Python", "FastAPI", "React", "Next.js"]),
        ("Software Engineer", "We use Python and React", "sent", ["Python", "React"]),
        ("Full Stack Developer (Python / React / AWS)", "", "sent", ["Python", "React"]),
        ("Engineer", "FastAPI backend, Next.js frontend", "sent", ["FastAPI", "Next.js"]),
        # 👀 partial: one side of the stack, or two bonus technologies
        ("Python Developer", "Django, PostgreSQL", "review", ["Python"]),
        ("Frontend Developer", "React and TypeScript", "review", ["React"]),
        ("AI Engineer", "LLM agents with LangChain on AWS", "review", []),
        # nothing matches
        ("DevOps Engineer", "Kubernetes, Terraform, CI/CD", "rejected_by_filter", []),
        ("Java Developer", "Spring Boot", "rejected_by_filter", []),
    ],
)
def test_tiers(title, description, moderation, stack):
    verdict = evaluate(Job(title=title, company="TechCorp", description=description))
    assert verdict.moderation == moderation
    assert verdict.stack == stack


def test_react_native_is_not_react():
    verdict = evaluate(Job(title="Mobile Developer", description="React Native, Python backend"))
    assert "React" not in verdict.stack
    assert verdict.moderation == "review"


def test_word_boundaries_avoid_substring_matches():
    # "ai" must not match inside "email", "sr" inside "srv", "python" is fine before a digit.
    assert title_reject_reason("Platform Engineer (srv)", None) is None
    verdict = evaluate(Job(title="Engineer", description="send an email; we use python3 and reactjs"))
    assert verdict.stack == ["Python", "React"]


def test_score_orders_more_stack_and_title_hits_first():
    all_four = evaluate(Job(title="Full Stack", description="python fastapi react next.js"))
    two = evaluate(Job(title="Full Stack", description="python react"))
    in_title = evaluate(Job(title="Python React Developer", description=""))
    assert all_four.score > two.score
    assert in_title.score > two.score


def test_prefilter_marks_rejected_and_returns_the_rest():
    storage = JobStorage()
    for job in [Job(title="Senior Python Dev"), Job(title="Python Developer"), Job(title="QA Engineer")]:
        storage.add_job(job)

    survivors = JobFilter(storage).prefilter_all()

    assert [job.title for job in survivors] == ["Python Developer"]
    assert storage.jobs[0].moderation == "rejected_by_filter"
    assert storage.jobs[0].filter_reason == "senior"


def test_classify_all_sets_fields_and_orders_best_first():
    storage = JobStorage()
    jobs = [
        Job(title="DevOps Engineer", description="Terraform"),
        Job(title="Python Developer", description="Django"),
        Job(title="Full Stack", description="Python FastAPI React"),
        Job(title="Senior Python Dev"),
        Job(title=None),
    ]
    for job in jobs:
        storage.add_job(job)

    JobFilter(storage).classify_all()

    assert len(storage.jobs) == len(jobs)
    assert [job.moderation for job in storage.jobs][:2] == ["sent", "review"]
    top = storage.jobs[0]
    assert top.matched_stack == ["Python", "FastAPI", "React"]
    assert top.filter_reason is None
    assert {job.filter_reason for job in storage.jobs[2:]} == {"no stack match", "senior"}


def test_classify_job_keeps_the_tuple_interface():
    assert JobFilter.classify_job(Job(title="Python React Developer")) == (
        "sent",
        30,
    )  # 2 core x10 + 2 core in title x5


@pytest.mark.parametrize(
    "location,rejected",
    [
        ("Remote only • India", True),
        ("In office • Bangalore", True),
        ("Remote only • Everywhere", False),
        ("Onsite or remote • Warsaw+1", False),
        (None, False),
    ],
)
def test_another_continent_is_not_a_remote_job_here(location, rejected):
    job = Job(title="Python Developer", location=location, description="Python FastAPI React")
    verdict = evaluate(job)

    assert (verdict.reason == "location") is rejected


def test_months_old_postings_are_dropped():
    old = Job(title="Python Developer", date=datetime.now() - timedelta(days=MAX_AGE_DAYS + 1))
    fresh = Job(title="Python Developer", date=datetime.now() - timedelta(days=3), description="Python React")

    assert evaluate(old).reason == "stale"
    assert evaluate(fresh).reason is None
    # A listener that could not parse the site's date gives a string — never guessed at.
    assert evaluate(Job(title="Python Developer", date="вчора", description="Python React")).reason is None


@pytest.mark.parametrize(
    "description,years",
    [
        ("Досвід роботи з Python від 5 років", 5),
        ("5+ years of experience with FastAPI", 5),
        ("Experience: 3-5 years with React", 3),
        ("We are on the market for 10 years of experience", None),  # not asked of you
        ("Опыт коммерческой разработки не менее 5 лет", 5),
        ("Python, FastAPI, React", None),
    ],
)
def test_required_years_reads_only_experience_lines(description, years):
    assert required_years(description) == years


def test_five_years_of_experience_is_a_senior_position_whatever_the_title_says():
    job = Job(title="Python Developer", description="Python FastAPI React\n5+ years of experience required")

    assert evaluate(job).reason == "senior"
