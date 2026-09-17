import html
import re
from datetime import datetime

from src.services.job_searcher.container import Job
from src.services.job_searcher.text import BULLET

_TIERS = {
    "sent": ("🔥", "Твой стек"),
    "review": ("👀", "Частично совпадает"),
}

# Rich messages allow 32768 characters including markup; the longest real descriptions are
# ~6000. The cap only guards against a page that dumped its whole footer into the block.
RICH_DESCRIPTION_LIMIT = 12_000
PREVIEW_LIMIT = 320
# Plain messages are capped at 4096 characters after entity parsing.
PLAIN_DESCRIPTION_LIMIT = 3_000

_HEADING_MAX = 60


def _date(job: Job) -> str | None:
    if not job.date:
        return None
    return job.date.strftime("%d.%m.%Y") if isinstance(job.date, datetime) else str(job.date)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > 0 else limit].rstrip() + " …"


def _looks_like_heading(line: str) -> bool:
    return len(line) <= _HEADING_MAX and not line.endswith((".", ",", ";")) and not line.startswith(BULLET)


def _paragraph_blocks(paragraph: str) -> list[str]:
    """One paragraph of the description: runs of "• " lines become a list, the rest prose."""
    blocks: list[str] = []
    prose: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if prose:
            if len(prose) == 1 and _looks_like_heading(prose[0]):
                blocks.append(f"<p><b>{html.escape(prose[0])}</b></p>")
            else:
                blocks.append("<p>" + "<br>".join(html.escape(line) for line in prose) + "</p>")
            prose.clear()
        if items:
            blocks.append("<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>")
            items.clear()

    for line in (raw.strip() for raw in paragraph.split("\n")):
        if not line:
            continue
        if line.startswith(BULLET):
            if prose:
                flush()
            items.append(line[len(BULLET) :])
        else:
            if items:
                flush()
            prose.append(line)
    flush()
    return blocks


def description_to_rich_html(text: str, limit: int = RICH_DESCRIPTION_LIMIT) -> str:
    """Paragraphs, lists and headings of a description (see services/job_searcher/text.py)."""
    return "".join(
        block for paragraph in re.split(r"\n{2,}", _truncate(text, limit)) for block in _paragraph_blocks(paragraph)
    )


def job_status_html(emoji: str, text: str, when: datetime) -> str:
    return f"{emoji} <b>{html.escape(text)}</b> — {when:%d.%m.%Y %H:%M}"


def job_to_rich_html(job: Job, status: str | None = None) -> str:
    """A vacancy as a Telegram rich message (sendRichMessage, HTML style).

    The conditions can be read without leaving Telegram: a short preview is visible, the full
    description is one tap away in a collapsed block, so a batch of vacancies stays scannable.
    """
    emoji, label = _TIERS.get(job.moderation or "", ("💼", ""))
    parts = [f"<h3>{emoji} {html.escape(job.title or 'Без названия')}</h3>"]

    date = _date(job)
    meta = [
        f"<b>{html.escape(job.company)}</b>" if job.company else None,
        html.escape(job.platform_name or ""),
        html.escape(date) if date else None,  # some listeners return the site's raw date string
    ]
    parts.append("<p>" + " · ".join(item for item in meta if item) + "</p>")

    if status:
        parts.append(f"<p>{status}</p>")

    if label:
        line = f"{emoji} <b>{label}</b>"
        if job.matched_stack:
            line += ": " + ", ".join(html.escape(name) for name in job.matched_stack)
        if job.matched_bonus:
            line += " · ещё " + ", ".join(html.escape(name) for name in job.matched_bonus)
        parts.append(f"<p>{line}</p>")

    if job.similar_to and job.similar_to_platform:
        parts.append(f"<p>🔁 Похоже, уже было на {html.escape(job.similar_to_platform)}</p>")

    if job.description:
        # The same for every tier: a preview to decide by, the full text folded. Open descriptions
        # took a whole screen each and a batch became a wall (the owner's call, 17.09.2026).
        preview = _truncate(" ".join(job.description.replace(BULLET, "").split()), PREVIEW_LIMIT)
        parts.append(f"<p>{html.escape(preview)}</p>")
        body = description_to_rich_html(job.description)
        parts.append(f"<details><summary>📄 Описание полностью</summary>{body}</details>")
    else:
        parts.append("<p><i>Описание площадка показывает только у себя — кнопка «Вакансия» ниже.</i></p>")

    parts.append(f"<footer>оценка {job.relevance_score}</footer>")
    return "".join(parts)


def job_to_html(job: Job) -> str:
    """Plain HTML fallback for when Telegram refuses the rich message."""
    title = html.escape(job.title or "")
    platform = html.escape(job.platform_name or "")
    company = html.escape(job.company or "")

    emoji, label = _TIERS.get(job.moderation or "", ("", ""))
    text = f"{emoji} {title} - {platform}\n" if emoji else f"{title} - {platform}\n"
    text += f"Company: <b>{company}</b>"

    if date := _date(job):
        text += f" Date: <i>{html.escape(date)}</i>"

    if label and job.matched_stack:
        text += f"\n{emoji} {label}: {html.escape(', '.join(job.matched_stack))}"

    if job.similar_to and job.similar_to_platform:
        text += f"\n🔁 Похоже, уже видел на {html.escape(job.similar_to_platform)}"

    if job.description:
        description_text = "\n".join(html.escape(_truncate(job.description, PLAIN_DESCRIPTION_LIMIT)).splitlines())
        text += f"\nDescription:\n<blockquote expandable>{description_text}</blockquote>"

    return text
