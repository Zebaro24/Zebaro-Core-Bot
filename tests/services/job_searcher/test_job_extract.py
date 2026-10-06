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
