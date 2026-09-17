import pytest

from src.services.job_searcher.container import Job, JobStorage
from src.services.job_searcher.filter import JobFilter, evaluate, title_reject_reason


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
        ("Junior Python Developer", "TechCorp", "junior"),
        ("Trainee Frontend (React)", "TechCorp", "junior"),
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
