from datetime import datetime, timedelta

import pytest

from src.services.job_searcher.container import Job, JobStorage
from src.services.job_searcher.filter import (
    MAX_AGE_DAYS,
    JobFilter,
    evaluate,
    reject_before_opening,
    required_years,
    title_level,
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
        ("AI Solutions Manager", "TechCorp", "not a developer role"),
        ("Business Analyst — AI Healthcare Project", "TechCorp", "not a developer role"),
        ("Application & AI Cyber Security Engineer", "TechCorp", "not a developer role"),
        ("Fullstack Team Leader", "TechCorp", "lead"),  # "lead" never matched "leader"
        ("Middle Full-Stack (React and C#)", "TechCorp", "other stack"),
        ("Full Stack Engineer (Python & Angular)", "TechCorp", "other stack"),
        ("Java Fullstack Developer", "TechCorp", "other stack"),
        (".Net Full-Stack Engineer (Angular)", "TechCorp", "other stack"),
        ("Full Stack Developer (Vue.js + Node.js)", "TechCorp", "other stack"),
        ("FullStack Developer (React+PHP Laravel)", "TechCorp", "other stack"),
        ("Full Stack Developer (React / React Native)", "TechCorp", "other stack"),
        ("Full Stack Mobile Developer (Cross-Platform / Native)", "TechCorp", "other stack"),
        ("Software Engineer (Golang, AI)", "TechCorp", "other stack"),
        ("Python Developer", "ФОП Іванов", "company"),
        ("Python Developer", "School ABC", "company"),
        ("Junior/Trainee React Developer", "TechCorp", "intern"),  # trainee is a skip, junior or not
        ("Trainee/Junior Full Stack JavaScript Developer (React/Node)", "Insiders", "intern"),
        ("Programming Instructor for Kids (Python, Roblox Studio, Unity)", "itkingdom", "not a developer role"),
        ("Інструктор із програмування для дітей 8-18 років (Python, AI)", "itkingdom", "not a developer role"),
        ("Data Analyst", "PRO.people", "not a developer role"),
        ("Customer Success Engineer", "YTC", "not a developer role"),
        ("Fullstack Developer до 1 окремий медичний батальйон", "1 окремий медичний батальйон", "military"),
        ("Software Engineer", "301 ОБТВР", "military"),
        ("Інженер БпЛА", "116 ОМБр", "military"),
        ("Python-розробник", "Військова частина А1234", "military"),
        ("Розробник у штурмова бригада", "TechCorp", "military"),
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
        "Full Stack Developer in Marketing team",  # "marketing" is the team, not the role
        "Freelance Next.js Developer - Marketing Site & Landing Pages",
        # Titles the owner answered — none of the new rules may catch them.
        "Middle JavaScript Full Stack Developer (Node + React)",  # JavaScript is not Java
        "Full-Stack Software Engineer (BE + FE / BE + Mobile)",
        "Fullstack Next.js / Nest.js Developer",
        "AEM Full Stack Developer",
        "Technical (Python) Support Engineer",
        "AI Research Scientist",
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
        ("DevOps Engineer", "Kubernetes, Terraform, CI/CD. " * 10, "rejected_by_filter", []),
        ("Java Developer", "Spring Boot", "rejected_by_filter", []),
    ],
)
def test_tiers(title, description, moderation, stack):
    verdict = evaluate(Job(title=title, company="TechCorp", description=description))
    assert verdict.moderation == moderation
    assert verdict.stack == stack


def test_react_native_is_not_react():
    verdict = evaluate(Job(title="Backend Engineer", description="React Native app, Python backend"))
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
        Job(title="DevOps Engineer", description="Terraform. " * 30),
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
        35,
    )  # 2 core x10 + 2 core in title x5 + 5 for the backend side


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


def test_four_years_of_experience_is_too_much_whatever_the_title_says():
    job = Job(title="Python Developer", description="Python FastAPI React\n4+ years of experience required")

    assert evaluate(job).reason == "experience"


@pytest.mark.parametrize(
    "title,level",
    [
        ("Middle Python Developer", "Middle"),
        ("Junior/Middle Full Stack", "Junior/Middle"),
        ("Middle/Senior Python Developer", "Middle/Senior"),
        ("Python Developer", None),
        (None, None),
    ],
)
def test_title_level(title, level):
    assert title_level(title) == level


def test_classify_all_keeps_the_required_years_for_the_message():
    storage = JobStorage()
    storage.add_job(Job(title="Full Stack", description="Python, React\nExperience: 3+ years"))

    JobFilter(storage).classify_all()

    assert storage.jobs[0].required_years == 3


@pytest.mark.parametrize(
    "location,reason",
    [
        ("In office • London", "office"),
        ("Dublin", "office"),
        ("Remote only • Argentina+7", "location"),
        ("Remote • United States", "location"),
        ("Remote only • Everywhere", None),
        ("Remote • Europe+2", None),
        ("Onsite or remote • London+1", None),
        (None, None),  # only Wellfound fills it; the rest must not be read as an office
    ],
)
def test_location_rules(location, reason):
    assert reject_before_opening(Job(title="Full Stack Developer", location=location)) == reason


_FULL = "Python, FastAPI and React on the job. " * 8  # long enough to count as a loaded page


def test_a_full_match_with_a_known_level_and_no_warnings_is_on_target():
    job = Job(title="Middle Full Stack Developer (Python / React)", description=_FULL)

    assert evaluate(job).moderation == "top"


@pytest.mark.parametrize(
    "fields",
    [
        {"english": "B2"},  # a warning keeps it out of the top
        {"platform_name": "Dou", "work_format": "remote"},  # remote without "за кордоном"
        {"title": "Full Stack Developer (Python / React)"},  # the level is not known
    ],
)
def test_anything_to_check_keeps_a_full_match_at_one_fire(fields):
    job = Job(**{"title": "Middle Full Stack Developer (Python / React)", "description": _FULL, **fields})

    assert evaluate(job).moderation == "sent"


@pytest.mark.parametrize(
    "fields,reason",
    [
        ({"work_format": "office"}, "office"),
        ({"work_format": "hybrid"}, "office"),
        ({"countries": "Україна"}, "country"),
        ({"countries": "Польща"}, "country"),
        ({"required_years": 4}, "experience"),
        ({"english": "C1"}, "english"),
    ],
)
def test_the_card_rejects_before_the_page_is_opened(fields, reason):
    assert reject_before_opening(Job(title="Python Developer", **fields)) == reason


@pytest.mark.parametrize("countries", ["Весь світ", "Країни Європи та Україна", "Країни ЄС", "за кордоном", None])
def test_countries_that_take_a_candidate_from_austria(countries):
    assert reject_before_opening(Job(title="Python Developer", countries=countries)) is None


@pytest.mark.parametrize(
    "description,reason",
    [
        ("Привіт! Ми шукаємо Senior / Lead Full Stack GenAI Engineer. " + _FULL, "senior"),
        ("English: Advanced (C1). " + _FULL, "english"),
        ("Робота в офісі у Києві. " + _FULL, "office"),
        ("5+ years of commercial experience\n3+ years with Go\n" + _FULL, "experience"),
    ],
)
def test_the_description_rejects_what_the_title_hid(description, reason):
    assert evaluate(Job(title="Full Stack Developer", description=description)).reason == reason


def test_a_senior_mentioned_beside_a_middle_is_not_a_senior_position():
    description = "We are looking for a senior or a strong middle engineer. " + _FULL

    assert evaluate(Job(title="Full Stack Developer", description=description)).reason is None


def test_plain_support_is_not_development_but_product_support_is():
    helpdesk = "Answer customer tickets and calls about the product, Python is a plus. " * 4
    product = "Fix bugs in our Python codebase and develop new features. " * 4

    assert evaluate(Job(title="Technical Support Engineer", description=helpdesk)).reason == "not a developer role"
    assert evaluate(Job(title="Фахівець технічна підтримка", description=helpdesk)).reason == "not a developer role"
    assert evaluate(Job(title="Technical (Python) Support Engineer", description=product)).moderation == "review"


def test_a_page_that_did_not_load_is_judged_by_the_title_not_rejected():
    verdict = evaluate(Job(title="Full Stack Developer", description=""))

    assert verdict.moderation == "review"
    assert "no_description" in verdict.warnings


def test_an_ai_title_is_worth_a_look_without_a_stack_in_the_text():
    description = "Build production systems with large models for our clients. " * 5

    assert evaluate(Job(title="AI Engineer", description=description)).moderation == "review"


def test_the_card_figures_win_over_the_description():
    job = Job(title="Full Stack Developer", description="5+ years of experience\n" + _FULL, required_years=2)

    assert evaluate(job).reason is None
