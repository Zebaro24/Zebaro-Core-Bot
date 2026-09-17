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
# A run of short lines is a list the site wrote with <br> instead of <ul> — the stack, the
# perks, the steps of the interview. Rendered as prose they become the wall of text the
# owner complained about.
_LIST_LINE_MAX = 110
_LIST_MIN_LINES = 3

# Bullets a description writes by hand, and numbered items ("1." / "1)").
_MANUAL_BULLET = re.compile(r"^[-–—*•●▪‣·]\s+")
_NUMBERED = re.compile(r"^\d{1,2}[.)]\s+")


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


def _looks_like_list(lines: list[str]) -> bool:
    return len(lines) >= _LIST_MIN_LINES and all(len(line) <= _LIST_LINE_MAX for line in lines)


def _list_html(items: list[str], ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + f"</{tag}>"


def _paragraph_blocks(paragraph: str) -> list[str]:
    """One paragraph of a description as rich blocks: headings, lists and prose.

    Telegram sets headings and list items apart on their own, so the more of the original
    structure survives here, the less the message looks like one block of text.
    """
    blocks: list[str] = []
    prose: list[str] = []
    items: list[str] = []
    ordered = False

    def flush() -> None:
        nonlocal ordered
        if prose:
            if len(prose) == 1 and _looks_like_heading(prose[0]):
                blocks.append(f"<h4>{html.escape(prose[0])}</h4>")
            elif _looks_like_list(prose):
                blocks.append(_list_html(prose))
            else:
                blocks.append("<p>" + "<br>".join(html.escape(line) for line in prose) + "</p>")
            prose.clear()
        if items:
            blocks.append(_list_html(items, ordered))
            items.clear()
        ordered = False

    for line in (raw.strip() for raw in paragraph.split("\n")):
        if not line:
            continue
        item, is_ordered = _list_item(line)
        if item is not None:
            if prose or (items and is_ordered != ordered):
                flush()
            ordered = is_ordered
            items.append(item)
        else:
            if items:
                flush()
            prose.append(line)
    flush()
    return blocks


def _list_item(line: str) -> tuple[str | None, bool]:
    """The line's text without its bullet, and whether the bullet was a number."""
    if line.startswith(BULLET):
        return line[len(BULLET) :], False
    if match := _MANUAL_BULLET.match(line):
        return line[match.end() :], False
    if match := _NUMBERED.match(line):
        return line[match.end() :], True
    return None, False


def description_to_rich_html(text: str, limit: int = RICH_DESCRIPTION_LIMIT) -> str:
    """Paragraphs, lists and headings of a description (see services/job_searcher/text.py)."""
    return "".join(
        block for paragraph in re.split(r"\n{2,}", _truncate(text, limit)) for block in _paragraph_blocks(paragraph)
    )


def job_status_html(emoji: str, text: str, when: datetime) -> str:
    return f"{emoji} <b>{html.escape(text)}</b> — {when:%d.%m.%Y %H:%M}"


def _preview(description: str) -> str:
    """The first lines of the description as one flat paragraph to decide by."""
    return _truncate(" ".join(description.replace(BULLET, "").split()), PREVIEW_LIMIT)


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
        html.escape(job.location) if job.location else None,
        html.escape(date) if date else None,  # some listeners return the site's raw date string
    ]
    parts.append("<p>" + " · ".join(item for item in meta if item) + "</p>")

    if status:
        parts.append(f"<p>{status}</p>")

    if label:
        line = f"{emoji} <b>{label}</b>"
        if job.matched_stack:
            # <mark> makes the reason the vacancy arrived readable at a glance while scrolling.
            line += ": " + " ".join(f"<mark>{html.escape(name)}</mark>" for name in job.matched_stack)
        if job.matched_bonus:
            line += " · ещё " + ", ".join(html.escape(name) for name in job.matched_bonus)
        parts.append(f"<p>{line}</p>")

    if job.similar_to and job.similar_to_platform:
        parts.append(f"<p>🔁 Похоже, уже было на {html.escape(job.similar_to_platform)}</p>")

    parts.append("<hr/>")

    if job.description:
        # The same for every tier: a preview to decide by, the full text folded. Open descriptions
        # took a whole screen each and a batch became a wall (the owner's call, 17.09.2026).
        parts.append(f"<blockquote>{html.escape(_preview(job.description))}</blockquote>")
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

    if job.location:
        text += f" 📍 {html.escape(job.location)}"

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
