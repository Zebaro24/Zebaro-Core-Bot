from datetime import datetime, timedelta

import pytest

from src.services.job_searcher import extract


@pytest.mark.parametrize(
    "description,years",
    [
        ("5+ years of commercial experience\n3+ years of production experience with Go", 5),  # the bar, not the minimum
        ("Experience: 3-5 years with React", 3),
        ("Досвід роботи від 4-х років", 4),
        ("• 2 years of commercial experience with Python", 2),
        ("You have 3 years of experience with FastAPI", 3),
        ("We are on the market for 10 years of experience", None),
        ("20+ years of experience in fintech, our team", None),  # nobody asks that of a candidate
        ("Python, FastAPI, React", None),
    ],
)
def test_required_years(description, years):
    assert extract.required_years(description) == years


@pytest.mark.parametrize(
    "text,level",
    [
        ("English: Upper-Intermediate", "B2"),
        ("B2+ English", "B2"),
        ("fluent spoken English (B2)", "B2"),  # a CEFR code wins over a word
        ("Fluent English", "B2"),  # written loosely on Ukrainian boards
        ("Англійська — Intermediate", "B1"),
        ("English level C1 or higher", "C1"),
        ("Python, React", None),
    ],
)
def test_english_level(text, level):
    assert extract.english_level(text) == level


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Англійська - B2", "B2"),
        ("Англійська - Немає", "none"),
        ("English - Upper", "B2"),
    ],
)
def test_card_english(text, expected):
    assert extract.card_english(text) == expected


@pytest.mark.parametrize(
    "text,years",
    [
        ("3 роки досвіду", 3),
        ("1 рік досвіду", 1),
        ("0.5 років досвіду", 0),
        ("3.5 роки досвіду", 3),
        ("Без досвіду", 0),
    ],
)
def test_card_years(text, years):
    assert extract.card_years(text) == years


@pytest.mark.parametrize(
    "text,fmt",
    [
        ("Тільки віддалено", "remote"),
        ("Тільки офіс", "office"),
        ("Гібридний формат роботи", "hybrid"),
        ("Офіс або віддалено", "office_or_remote"),
        ("Fintech", None),
    ],
)
def test_work_format(text, fmt):
    assert extract.work_format(text) == fmt


@pytest.mark.parametrize(
    "countries,ok",
    [
        ("Весь світ", True),
        ("Країни Європи та Україна", True),
        ("Країни ЄС", True),
        ("Україна", False),
        ("Україна (Київ)", False),
        ("Ізраїль, Польща, Україна", False),
        (None, None),
    ],
)
def test_abroad_ok(countries, ok):
    assert extract.abroad_ok(countries) is ok


def test_ukraine_only_reads_the_candidate_not_the_company():
    assert extract.ukraine_only_text("Candidates must be located in Ukraine")
    assert extract.ukraine_only_text("Обов'язково перебування в Україні")
    assert not extract.ukraine_only_text("A Ukrainian product company with offices in Kyiv")


@pytest.mark.parametrize(
    "text,delta",
    [
        ("2 дні тому", timedelta(days=2)),
        ("19 годин тому", timedelta(hours=19)),
        ("1 тиждень тому", timedelta(weeks=1)),
        ("тиждень тому", timedelta(weeks=1)),
        ("4 тижні тому", timedelta(weeks=4)),
        ("1 місяць тому", timedelta(days=30)),
        ("3 days ago", timedelta(days=3)),
        ("5 хвилин тому", timedelta(minutes=5)),
    ],
)
def test_relative_date(text, delta):
    now = datetime(2026, 10, 6, 12)

    assert extract.relative_date(text, now) == now - delta


def test_relative_date_without_a_date():
    assert extract.relative_date("Гаряча вакансія") is None


def test_card_applicants():
    assert extract.card_applicants("227 відгуків") == 227
    assert extract.card_applicants("1878 переглядів") is None


@pytest.mark.parametrize(
    "description,plus_only",
    [
        ("Requirements:\n• Node.js\n\nNice to have:\n• Python", True),
        ("Вимоги:\n• Node.js\n\nБуде плюсом:\n• Django", True),
        ("• Node.js, React\n• Python would be a plus", True),
        ("Requirements:\n• Python\n\nNice to have:\n• Python typing", False),
        ("We use Python and React.", False),
        ("Nice to have:\n• Go\n\nRequirements:\n• Python", False),  # a new heading closes the section
        ("No language named here.", False),
        ("Requirements:\n• Node.js\n\nNice to have:\nPython", True),  # an item without a bullet
    ],
)
def test_only_as_plus(description, plus_only):
    assert extract.only_as_plus(description, ("python", "django")) is plus_only


# --- the brief ---------------------------------------------------------------------------------

DJINNI_EN = """About us
We are a fast-growing AI startup with a friendly culture.

Responsibilities:
• Build LLM agents
• Strong skills in code review

Requirements:
• 3+ years of commercial experience with Python
• FastAPI, PostgreSQL
• Experience with interview tools is fine
• English B2+

Nice to have:
• LangChain

We offer:
• Remote work, 20 days off
"""

DOU_UK = """Про компанію
Ми продуктова компанія.

Що ми очікуємо
- Досвід з Python від 2 років
- Розуміння REST

Обов'язки
- Писати сервіси

Що ми пропонуємо
- Гнучкий графік
"""


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (
            DJINNI_EN,
            "• 3+ years of commercial experience with Python\n• FastAPI, PostgreSQL\n"
            "• Experience with interview tools is fine\n• English B2+",
        ),
        (DOU_UK, "- Досвід з Python від 2 років\n- Розуміння REST"),
        ("Требования:\n- Django\n- Docker\nМы предлагаем:\n- ДМС", "- Django\n- Docker"),
        ("Requirements: Python, SQL\nWhat we offer: a team", "Python, SQL"),  # the list on the heading's line
        ("1. Requirements\n- Go\n2. Benefits\n- Gym", "- Go"),  # a numbered heading
        ("We build things in Python. You will love it.", None),  # no heading: read the full text
        ("Strong skills in Python and SQL are needed for this role\n- Go", None),  # a long line opens nothing
        (None, None),
    ],
    ids=["en", "uk", "ru", "inline", "numbered", "no heading", "a body line naming skills", "no text"],
)
def test_requirements_are_the_must_have_section(description, expected):
    assert extract.requirements(description) == expected


DJINNI_SUBSECTIONS = """We’re looking for an AI Automation Developer with strong Python fundamentals.

What you’ll do

• Build and maintain n8n workflows.

What we’re looking for

Strong Python fundamentals

• You can confidently write and explain Python code.
• You can work with APIs, process JSON, and build a backend service using FastAPI.

Hands-on automation and AI experience

• You have built working n8n workflows.

Nice to have

• Experience with React.

What we offer

• Paid vacation.
"""


def test_a_typographic_apostrophe_and_sub_headings_keep_the_section():
    # The shape of a real Djinni text (robomate, 17.11.2026): "we’re", and sub-headings inside.
    assert extract.requirements(DJINNI_SUBSECTIONS) == (
        "Strong Python fundamentals\n"
        "• You can confidently write and explain Python code.\n"
        "• You can work with APIs, process JSON, and build a backend service using FastAPI.\n"
        "Hands-on automation and AI experience\n"
        "• You have built working n8n workflows."
    )


BARE_LINES = """What you will do:
You are going to build APIs
Design services in FastAPI
Requirements:
You have 3+ years with Python
Required English B2
Solid SQL
Plus:
Kubernetes
"""


def test_lines_without_bullets_are_not_taken_for_headings():
    # The reviewer's case: short plain lines naming "you are", "you have", "required" are body lines.
    assert extract.requirements(BARE_LINES) == "You have 3+ years with Python\nRequired English B2\nSolid SQL"


@pytest.mark.parametrize(
    "heading",
    ["Required skills", "What we're looking for", "Що ми очікуємо", "Requirements", "🔹 Вимоги до кандидата"],
)
def test_a_heading_without_a_colon_still_opens_the_section(heading):
    assert extract.requirements(f"{heading}\n- Python\nWe offer\n- Gym") == "- Python"


def test_requirements_are_cut_at_the_limit():
    description = "Requirements:\n" + "\n".join(f"- skill number {i} " + "x" * 80 for i in range(40))

    text = extract.requirements(description)

    assert text is not None
    assert len(text.splitlines()) <= extract.REQUIREMENTS_MAX_LINES
    assert len(text) <= extract.REQUIREMENTS_MAX_CHARS


@pytest.mark.parametrize(
    ("description", "hours"),
    [
        ("Remote\n• Overlap with CET 10:00–14:00\n• Python", ["Overlap with CET 10:00–14:00"]),
        ("Часовий пояс: Київ ±2 години\nГрафік: 10:00-19:00", ["Часовий пояс: Київ ±2 години", "Графік: 10:00-19:00"]),
        ("Work 40 hours per week, US time zone (EST)", ["Work 40 hours per week, US time zone (EST)"]),
        ("Python, FastAPI, 3+ years", []),
        ("est. 2015, we are the best", []),  # "est." of a founding year is a word, not a zone
        ("Vacation 01.12 - 15.12", []),  # a date range
        ("Робочий день 10.00-19.00", ["Робочий день 10.00-19.00"]),
        ("Flexible schedule, remote", ["Flexible schedule, remote"]),
    ],
    ids=["overlap", "uk schedule", "hours per week", "none", "est as a word", "dates", "dotted hours", "flexible"],
)
def test_work_hours_are_the_lines_about_time(description, hours):
    assert extract.work_hours(description) == hours
