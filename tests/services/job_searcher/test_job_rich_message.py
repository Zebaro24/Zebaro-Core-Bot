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
    assert "<p><b>Requirements</b></p>" in body
    assert "<ul><li>3+ years with Python</li><li>FastAPI and &lt;React&gt;</li></ul>" in body
    assert "<p><b>What we offer:</b></p>" in body
    assert "<p>Remote work.<br>Flexible hours.</p>" in body


def test_description_is_truncated_on_a_line_boundary():
    body = description_to_rich_html("line one\n" * 50, limit=100)
    assert body.endswith("…</p>")
    assert len(body) < 200


def test_your_stack_message_says_why_and_folds_the_description():
    text = job_to_rich_html(_job())

    assert text.startswith("<h3>🔥 Full Stack Developer</h3>")
    assert "<p><b>Acme</b> · Dou · 17.09.2026</p>" in text
    assert "🔥 <b>Твой стек</b>: Python, FastAPI, React · ещё TypeScript" in text
    assert "<p>We build a data product. Requirements 3+ years with Python" in text
    assert "<details><summary>📄 Описание полностью</summary><p>We build" in text
    assert "<details open>" not in text
    assert text.endswith("<footer>оценка 45</footer>")


def test_partial_match_uses_the_same_layout_without_the_old_label():
    text = job_to_rich_html(_job(moderation="review", matched_stack=["Python"], matched_bonus=[]))

    assert "👀 <b>Частично совпадает</b>: Python" in text
    assert "проверь сам" not in text
    assert "<details><summary>📄 Описание полностью</summary><p>We build" in text


def test_missing_description_points_to_the_button():
    text = job_to_rich_html(_job(description=None))
    assert "кнопка «Вакансия»" in text


def test_status_goes_right_under_the_company_line():
    status = job_status_html("✅", "Откликнулся", datetime(2026, 9, 17, 14, 5))
    text = job_to_rich_html(_job(), status=status)

    assert "<p>✅ <b>Откликнулся</b> — 17.09.2026 14:05</p>" in text
    assert text.index("Откликнулся") < text.index("Твой стек")


def test_everything_user_provided_is_escaped():
    text = job_to_rich_html(_job(title="<script>", company="A&B", similar_to="x", similar_to_platform="<b>"))

    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "A&amp;B" in text
    assert "уже было на &lt;b&gt;" in text


def test_plain_fallback_fits_a_telegram_message():
    text = job_to_html(_job(description="word " * 5000))
    assert len(text) < 4096
    assert len(text) > PLAIN_DESCRIPTION_LIMIT
