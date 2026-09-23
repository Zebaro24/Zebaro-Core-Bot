from datetime import datetime
from typing import Any

from src.interfaces.tg.formatters.job import (
    PLAIN_DESCRIPTION_LIMIT,
    description_to_rich_html,
    job_status_html,
    job_to_html,
    job_to_rich_html,
)
from src.services.job_searcher.container import Job

DESCRIPTION = (
    "We build a data product.\n\n"
    "Requirements\n\n"
    "• 3+ years with Python\n• FastAPI and <React>\n\n"
    "What we offer:\n\n"
    "Remote work.\nFlexible hours."
)


def _job(**overrides: Any) -> Job:
    base: dict[str, Any] = dict(
        title="Full Stack Developer",
        company="Acme",
        platform_name="Dou",
        date=datetime(2026, 9, 17),
        description=DESCRIPTION,
        moderation="sent",
        relevance_score=45,
        matched_stack=["Python", "FastAPI", "React"],
        matched_bonus=["TypeScript"],
    )
    base.update(overrides)
    return Job(**base)


def test_description_keeps_paragraphs_lists_and_headings():
    body = description_to_rich_html(DESCRIPTION)

    assert "<p>We build a data product.</p>" in body
    assert "<h4>Requirements</h4>" in body
    assert "<ul><li>3+ years with Python</li><li>FastAPI and &lt;React&gt;</li></ul>" in body
    assert "<h4>What we offer:</h4>" in body
    assert "<p>Remote work.<br>Flexible hours.</p>" in body


def test_hand_written_bullets_and_numbers_become_lists():
    body = description_to_rich_html("Що треба:\n\n- Python\n— FastAPI\n* React\n\nЯк наймаємо:\n\n1. Дзвінок\n2) Тест")

    assert "<ul><li>Python</li><li>FastAPI</li><li>React</li></ul>" in body
    assert "<ol><li>Дзвінок</li><li>Тест</li></ol>" in body


def test_a_run_of_short_lines_is_shown_as_a_list_not_a_wall():
    # The stack the site wrote with <br> instead of <ul> — three lines or more, all short.
    body = description_to_rich_html("Python, FastAPI.\nБази даних: PostgreSQL.\nДеплой: Docker.")

    assert body == "<ul><li>Python, FastAPI.</li><li>Бази даних: PostgreSQL.</li><li>Деплой: Docker.</li></ul>"


def test_two_lines_stay_a_paragraph():
    body = description_to_rich_html("Remote work.\nFlexible hours.")
    assert body == "<p>Remote work.<br>Flexible hours.</p>"


def test_description_is_truncated_on_a_line_boundary():
    body = description_to_rich_html("line one\n" * 50, limit=100)
    assert body.endswith("…</li></ul>")
    assert len(body) < 400


def test_your_stack_message_says_why_and_folds_the_description():
    text = job_to_rich_html(_job())

    assert text.startswith("<h3>🔥 Full Stack Developer</h3>")
    assert "<p><b>Acme</b> · Dou · 17.09.2026</p>" in text
    assert (
        "<p>🔥 <b>Бэк + фронт</b> — <mark>Python</mark>, <mark>FastAPI</mark> · <mark>React</mark>"
        "<br>➕ TypeScript</p>"
    ) in text
    assert "<hr/><blockquote>We build a data product. Requirements 3+ years with Python" in text
    assert "<details><summary>📄 Описание полностью</summary><p>We build" in text
    assert "<details open>" not in text
    assert "оценка" not in text  # an internal number for ordering, it told the owner nothing


def test_partial_match_uses_the_same_layout_without_the_old_label():
    text = job_to_rich_html(_job(moderation="review", matched_stack=["Python"], matched_bonus=[]))

    assert "<p>👀 <b>Бэкенд</b> — <mark>Python</mark></p>" in text
    assert "проверь сам" not in text
    assert "<details><summary>📄 Описание полностью</summary><p>We build" in text


def test_location_stands_next_to_the_company():
    text = job_to_rich_html(_job(location="Remote only • Everywhere"))
    assert "<p><b>Acme</b> · Dou · Remote only • Everywhere · 17.09.2026</p>" in text


def test_missing_description_points_to_the_button():
    text = job_to_rich_html(_job(description=None))
    assert "кнопка «Вакансия»" in text


def test_status_goes_right_under_the_company_line():
    status = job_status_html("✅", "Откликнулся", datetime(2026, 9, 17, 14, 5))
    text = job_to_rich_html(_job(), status=status)

    assert "<p>✅ <b>Откликнулся</b> — 17.09.2026 14:05</p>" in text
    assert text.index("Откликнулся") < text.index("Бэк + фронт")


def test_why_names_the_half_of_the_stack_that_matched():
    frontend = job_to_rich_html(_job(moderation="review", matched_stack=["React", "Next.js"], matched_bonus=[]))
    assert "👀 <b>Фронтенд</b> — <mark>React</mark>, <mark>Next.js</mark>" in frontend

    # Only bonus technologies: they are the reason, not an extra line.
    related = job_to_rich_html(_job(moderation="review", matched_stack=[], matched_bonus=["TypeScript", "Docker"]))
    assert "👀 <b>Смежный стек</b> — <mark>TypeScript</mark>, <mark>Docker</mark></p>" in related
    assert "➕" not in related


def test_why_shows_the_experience_and_the_level():
    text = job_to_rich_html(_job(title="Middle Full Stack Developer", required_years=3))
    assert "<br>🎓 от 3 лет · Middle</p>" in text

    assert "🎓 от 1 года · Junior/Middle" in job_to_rich_html(_job(title="Junior/Middle Dev", required_years=1))
    assert "🎓 Junior" in job_to_rich_html(_job(title="Junior Python Developer"))
    assert "🎓" not in job_to_rich_html(_job())  # the title and the description said nothing


def test_everything_user_provided_is_escaped():
    text = job_to_rich_html(
        _job(
            title="<script>",
            company="A&B",
            date="<i>вчора</i>",
            location="<b>Kyiv</b>",
            similar_to="x",
            similar_to_platform="<b>",
        )
    )

    assert "<script>" not in text
    assert "&lt;i&gt;вчора&lt;/i&gt;" in text
    assert "&lt;script&gt;" in text
    assert "A&amp;B" in text
    assert "&lt;b&gt;Kyiv&lt;/b&gt;" in text
    assert "уже было на &lt;b&gt;" in text


def test_plain_fallback_fits_a_telegram_message():
    text = job_to_html(_job(description="word " * 5000))
    assert len(text) < 4096
    assert len(text) > PLAIN_DESCRIPTION_LIMIT
