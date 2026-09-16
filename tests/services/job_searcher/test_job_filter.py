import pytest

from src.services.job_searcher.container import Job, JobStorage
from src.services.job_searcher.filter import JobFilter


@pytest.mark.parametrize(
    "title,company,expected_moderation,expected_score",
    [
        ("QA Engineer Python", "TechCorp", "rejected_by_filter", 0),
        ("AI Training Data Labeling", "TechCorp", "rejected_by_filter", 0),
        ("Python Developer", "ФОП Іванов", "rejected_by_filter", 0),
        ("Python Developer", "School ABC", "rejected_by_filter", 0),
    ],
)
def test_classify_job_hard_reject(title, company, expected_moderation, expected_score):
    job = Job(title=title, company=company)
    moderation, score = JobFilter.classify_job(job)
    assert moderation == expected_moderation
    assert score == expected_score


def test_classify_job_frontend_only_rejected():
    job = Job(title="Frontend Developer (React)")
    moderation, _ = JobFilter.classify_job(job)
    assert moderation == "rejected_by_filter"


def test_classify_job_frontend_with_backend_signal_not_auto_rejected():
    job = Job(title="Fullstack Frontend Developer")
    moderation, score = JobFilter.classify_job(job)
    assert moderation == "sent"
    assert score == 6


def test_classify_job_junior_without_middle_rejected():
    job = Job(title="Junior Python Developer")
    moderation, _ = JobFilter.classify_job(job)
    assert moderation == "rejected_by_filter"


def test_classify_job_junior_middle_not_rejected_by_junior_rule():
    job = Job(title="Junior/Middle Python Developer")
    moderation, score = JobFilter.classify_job(job)
    assert moderation == "sent"
    assert score > 0


def test_classify_job_senior_without_ai_rejected():
    job = Job(title="Senior Python Developer")
    moderation, _ = JobFilter.classify_job(job)
    assert moderation == "rejected_by_filter"


def test_classify_job_word_boundary_avoids_false_positive_substring():
    # "ai" не должен матчить внутри "Container" — регрессия на баг с наивным substring-поиском.
    job = Job(title="Senior Container Platform Engineer")
    moderation, score = JobFilter.classify_job(job)
    assert moderation == "rejected_by_filter"
    assert score == 0


def test_classify_job_word_boundary_still_matches_standalone_ai():
    job = Job(title="Senior AI/ML Engineer")
    moderation, score = JobFilter.classify_job(job)
    assert moderation != "rejected_by_filter"
    assert score > 0


def test_classify_job_senior_with_ai_signal_goes_to_scoring():
    job = Job(title="Senior AI Engineer")
    moderation, score = JobFilter.classify_job(job)
    assert moderation == "review"
    assert score == 4


def test_classify_job_middle_title_not_hard_rejected():
    # Bug fix: старый фильтр резал любой тайтл с "middle", что противоречит профилю пользователя.
    job = Job(title="Middle Python Developer")
    moderation, score = JobFilter.classify_job(job)
    assert moderation == "sent"
    assert score > 0


def test_classify_job_ai_native_title_not_requiring_python():
    # Bug fix: старый фильтр требовал "python"/"full" в тайтле.
    job = Job(title="Product Engineer (AI-first)")
    moderation, score = JobFilter.classify_job(job)
    assert moderation in ("sent", "review")
    assert score > 0


def test_classify_job_high_score_sent():
    job = Job(title="Python Fullstack Engineer")
    moderation, score = JobFilter.classify_job(job)
    assert moderation == "sent"
    assert score == 12


def test_classify_job_no_signals_rejected_by_score():
    job = Job(title="DevOps Engineer", description="Kubernetes, Terraform, CI/CD")
    moderation, score = JobFilter.classify_job(job)
    assert moderation == "rejected_by_filter"
    assert score == 0


def test_classify_job_description_contributes_to_score():
    job = Job(title="Software Engineer", description="We use Python and FastAPI every day")
    moderation, score = JobFilter.classify_job(job)
    assert score == 5  # python(3) + fastapi(2), weight x1 from description
    assert moderation == "sent"


def test_classify_all_keeps_all_jobs_and_sets_fields():
    storage = JobStorage()
    jobs = [
        Job(title="Senior Python Dev", company="TechCorp"),
        Job(title="Python Fullstack Engineer", company="TechCorp"),
        Job(title="DevOps Engineer", company="TechCorp"),
        Job(title=None, company="TechCorp"),
    ]
    for job in jobs:
        storage.add_job(job)

    JobFilter(storage).classify_all()

    assert len(storage.jobs) == len(jobs)
    for job in storage.jobs:
        assert job.moderation in ("sent", "review", "rejected_by_filter")
        assert isinstance(job.relevance_score, int)
