import html
import re
from collections.abc import Callable
from datetime import datetime

from src.services.job_searcher.container import Job
from src.services.job_searcher.filter import (
    BACKEND_CORE,
    BONUS_STACK,
    CORE_STACK,
    FRONTEND_CORE,
    OTHER_STACK_WORDS,
    keyword_pattern,
    title_level,
)
from src.services.job_searcher.text import BULLET

_TIERS = {
    "top": "🔥🔥🔥",
    "sent": "🔥",
    "review": "👀",
}

_FORMATS = {"remote": "Удалённо", "office_or_remote": "Офис или удалённо", "hybrid": "Гибрид", "office": "Офис"}
_WARNINGS = {
    "english": "просят английский B2",
    "ukraine": "в тексте про нахождение в Украине",
    "no_description": "стек не проверен — сужу только по названию",
    "no_python": "Python в тексте не упомянут",
    "python_plus": "Python только «будет плюсом» — основной стек другой",
}

# What the description says about the stack, marked where it says it (22.10.2026): the core
# stack, the bonus one, and what may not fit — another main stack, 4+ years, senior, an English
# above B1, an office.
# Plain "go" and "lead" are English words first ("go live", "lead the feature") — left out.
_FLAG_WORDS = (
    *OTHER_STACK_WORDS, "node.js", "nodejs", "nestjs", "nest.js", "rust", "c++",
    "senior", "team lead", "tech lead", "офіс", "office", "on-site", "onsite", "hybrid", "гібрид",
)  # fmt: skip
_FLAG_EXTRA = (
    r"(?<!\d)(?:[4-9]|1\d)\s*\+?\s*(?:years?|yrs?|років|роки|рік|лет|года)",  # "5+ years", "від 4 років"
    r"\b(?:b2|c1|c2|upper[- ]intermediate)\b",
    r"\b(?:fluent|advanced)\s+english\b",
)


def _alternation(words: list[str]) -> str:
    # Longest first: "team lead" before "lead", "react.js" before "react".
    return "|".join(keyword_pattern(word) for word in sorted(set(words), key=len, reverse=True))


_HIGHLIGHT = re.compile(
    "(?P<core>{})|(?P<bonus>{})|(?P<flag>{})".format(
        _alternation([word for words in CORE_STACK.values() for word in words]),
        _alternation([word for words in BONUS_STACK.values() for word in words]),
        "|".join([_alternation(list(_FLAG_WORDS)), *_FLAG_EXTRA]),
    ),
    re.IGNORECASE,
)
# Rich messages have <mark>; plain HTML does not.
RICH_MARKS = {"core": "mark", "bonus": "b", "flag": "u"}
PLAIN_MARKS = {"core": "b", "bonus": "i", "flag": "u"}


def highlight(text: str, marks: dict[str, str] = RICH_MARKS) -> str:
    """Escape the text and wrap every stack word and red flag in its tag."""
    parts, end = [], 0
    for match in _HIGHLIGHT.finditer(text):
        tag = marks[match.lastgroup or "core"]
        parts += [html.escape(text[end : match.start()]), f"<{tag}>{html.escape(match.group())}</{tag}>"]
        end = match.end()
    parts.append(html.escape(text[end:]))
    return "".join(parts)


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


def _list_html(items: list[str], ordered: bool = False, escape: Callable[[str], str] = html.escape) -> str:
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{escape(item)}</li>" for item in items) + f"</{tag}>"


def _paragraph_blocks(paragraph: str, escape: Callable[[str], str] = html.escape) -> list[str]:
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
                blocks.append(f"<h4>{escape(prose[0])}</h4>")
            elif _looks_like_list(prose):
                blocks.append(_list_html(prose, escape=escape))
            else:
                blocks.append("<p>" + "<br>".join(escape(line) for line in prose) + "</p>")
            prose.clear()
        if items:
            blocks.append(_list_html(items, ordered, escape))
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


def description_to_rich_html(text: str, limit: int = RICH_DESCRIPTION_LIMIT, marked: bool = False) -> str:
    """Paragraphs, lists and headings of a description (see services/job_searcher/text.py).

    `marked` highlights the stack and the red flags in the text (`highlight`).
    """
    escape = highlight if marked else html.escape
    return "".join(
        block
        for paragraph in re.split(r"\n{2,}", _truncate(text, limit))
        for block in _paragraph_blocks(paragraph, escape)
    )


def _years(years: int) -> str:
    if years == 0:
        return "без опыта"
    return f"от {years} года" if years % 10 == 1 and years % 100 != 11 else f"от {years} лет"


def _applicants(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        word = "отклик"
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = "отклика"
    else:
        word = "откликов"
    return f"{count} {word}"


def conditions_line(job: Job) -> str | None:
    """What the vacancy asks and offers, in one line: 📍 Удалённо · Весь світ · 🗣 B2 · 💰 до $2500."""
    # DOU without "за кордоном": usually a forgotten tick, worth a glance, not an alarm.
    abroad = "за кордон не отмечен" if "abroad" in job.warnings else ""
    place = [_FORMATS.get(job.work_format or "", ""), job.countries or abroad]
    english = "без английского" if job.english == "none" else job.english
    items = [
        "📍 " + " · ".join(item for item in place if item) if any(place) else None,
        f"🗣 {english}" if english else None,
        f"💰 {job.salary}" if job.salary else None,
        f"👥 {_applicants(job.applicants)}" if job.applicants is not None else None,
    ]
    line = " · ".join(item for item in items if item)
    return html.escape(line) if line else None


def warnings_line(job: Job) -> str | None:
    texts = [_WARNINGS[warning] for warning in job.warnings if warning in _WARNINGS]
    return "⚠️ " + html.escape("; ".join(texts)) if texts else None


def _why_lines(job: Job, emoji: str, mark: bool) -> list[str]:
    """Why the vacancy came, in two or three short lines (the owner's pick, 23.09.2026):

    🔥 Бэк + фронт — Python, FastAPI · React
    ➕ TypeScript, Docker, LLM
    🎓 от 3 лет · Middle
    """

    def names(items: list[str]) -> str:
        if mark:
            # <mark> makes the reason the vacancy arrived readable at a glance while scrolling.
            return ", ".join(f"<mark>{html.escape(name)}</mark>" for name in items)
        return html.escape(", ".join(items))

    backend = [name for name in job.matched_stack if name in BACKEND_CORE]
    frontend = [name for name in job.matched_stack if name in FRONTEND_CORE]
    bonus = list(job.matched_bonus)
    if backend and frontend:
        head, groups = "Бэк + фронт", [backend, frontend]
    elif backend:
        head, groups = "Бэкенд", [backend]
    elif frontend:
        head, groups = "Фронтенд", [frontend]
    else:
        # Two bonus technologies with no core one: they are the whole reason, not an extra.
        head, groups, bonus = "Смежный стек", [bonus], []

    lines = []
    if any(groups):
        lines.append(f"{emoji} <b>{head}</b> — " + " · ".join(names(group) for group in groups if group))
    if bonus:
        lines.append("➕ " + html.escape(", ".join(bonus)))
    experience = [_years(job.required_years) if job.required_years is not None else None, title_level(job.title)]
    if any(experience):
        lines.append("🎓 " + html.escape(" · ".join(item for item in experience if item)))
    return lines


def repeat_line(job: Job) -> str | None:
    """What the owner already saw of this vacancy (services/job_searcher/dedup.py)."""
    if not job.similar_to or not job.similar_to_platform:
        return None
    platform = html.escape(job.similar_to_platform)
    when = f" {job.similar_seen_at:%d.%m}" if isinstance(job.similar_seen_at, datetime) else ""
    opened = " · 👁 ссылку уже открывал" if job.similar_clicked else ""
    if job.similar_status == "blocked":
        return f"⛔ На {platform}{when} не пустило — это та же вакансия здесь{opened}"
    if job.similar_status == "pending":
        return f"🔁 Уже присылал{when} с {platform} — без ответа, кнопки отметят обе{opened}"
    # Documents from before groups: only that a copy existed.
    return f"🔁 Похоже, уже было на {platform}{opened}"


_HISTORY_STATUS = {
    "applied": "✅ откликался",
    "not_interested": "👎 отказался",
    "mismatch": "🚫 не прошёл",
    "blocked": "⛔ сайт не пустил",
    "pending": "👁 открывал",
}
HISTORY_SHOWN = 3


def history_lines(job: Job) -> list[str]:
    """What the owner did with this company's other vacancies (services/job_searcher/dedup.py)."""
    lines = []
    for entry in job.company_history[:HISTORY_SHOWN]:
        status = _HISTORY_STATUS.get(entry.get("status") or "", "")
        when = f" {entry['at']:%d.%m}" if isinstance(entry.get("at"), datetime) else ""
        same = " — похоже, это она же" if entry.get("similar") else ""
        lines.append(f"📌 {status}{when}: «{html.escape(entry.get('title') or '')}»{same}")
    if len(job.company_history) > HISTORY_SHOWN:
        lines.append(f"📌 …и ещё {len(job.company_history) - HISTORY_SHOWN} в этой компании")
    return lines


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
    emoji = _TIERS.get(job.moderation or "", "💼")
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

    if job.moderation in _TIERS:
        lines = _why_lines(job, emoji, mark=True)
        lines += [line for line in (conditions_line(job), warnings_line(job)) if line]
        if lines:
            parts.append("<p>" + "<br>".join(lines) + "</p>")

    seen = [line for line in (repeat_line(job), *history_lines(job)) if line]
    if seen:
        parts.append("<p>" + "<br>".join(seen) + "</p>")

    parts.append("<hr/>")

    if job.description:
        # The same for every tier: a preview to decide by, the full text folded. Open descriptions
        # took a whole screen each and a batch became a wall (the owner's call, 17.09.2026).
        parts.append(f"<blockquote>{highlight(_preview(job.description))}</blockquote>")
        body = description_to_rich_html(job.description, marked=True)
        parts.append(f"<details><summary>📄 Описание полностью</summary>{body}</details>")
    else:
        parts.append("<p><i>Описание не подтянулось — открой его кнопкой «Вакансия» ниже.</i></p>")

    return "".join(parts)


def _summary_item(job: Job, rich: bool) -> str:
    """ "AI Engineer — Acme · Dou · Python, LLM · ⚠️ 1 · 📌" in one line."""
    stack = [*job.matched_stack, *job.matched_bonus]
    bits = [
        html.escape(job.company) if job.company else None,
        html.escape(job.platform_name or "") or None,
        html.escape(", ".join(stack)) if stack else None,
        "⚠️ " + html.escape(", ".join(_WARNINGS[w] for w in job.warnings if w in _WARNINGS))
        if any(w in _WARNINGS for w in job.warnings)
        else None,
        "🔁" if job.similar_to else None,
        "📌 компания знакома" if job.company_history else None,
    ]
    title = html.escape(job.title or "Без названия")
    head = f"<b>{title}</b>" if rich else title
    return head + " — " + " · ".join(bit for bit in bits if bit)


def review_summary_html(jobs: list[Job], first_number: int = 1, total: int | None = None) -> str:
    """The 👀 tier of a run as one message (22.10.2026): partial matches no longer arrive one by
    one between the vacancies on target. A button under it opens any of them in full."""
    total = total if total is not None else len(jobs)
    # Numbered by hand, not <ol>: the numbers are the buttons', and a later part starts past 1.
    items = "".join(f"<p>{n}. {_summary_item(job, rich=True)}</p>" for n, job in enumerate(jobs, first_number))
    return f"<h3>👀 Частичные совпадения — {total}</h3>{items}"


def review_summary_plain(jobs: list[Job], first_number: int = 1, total: int | None = None) -> str:
    total = total if total is not None else len(jobs)
    lines = [f"{n}. {_summary_item(job, rich=False)}" for n, job in enumerate(jobs, first_number)]
    return f"👀 <b>Частичные совпадения — {total}</b>\n" + "\n".join(lines)


def job_to_html(job: Job) -> str:
    """Plain HTML fallback for when Telegram refuses the rich message."""
    title = html.escape(job.title or "")
    platform = html.escape(job.platform_name or "")
    company = html.escape(job.company or "")

    emoji = _TIERS.get(job.moderation or "", "")
    text = f"{emoji} {title} - {platform}\n" if emoji else f"{title} - {platform}\n"
    text += f"Company: <b>{company}</b>"

    if job.location:
        text += f" 📍 {html.escape(job.location)}"

    if date := _date(job):
        text += f" Date: <i>{html.escape(date)}</i>"

    if emoji:
        why = _why_lines(job, emoji, mark=False) + [line for line in (conditions_line(job), warnings_line(job)) if line]
        if why:
            text += "\n" + "\n".join(why)

    for line in (repeat_line(job), *history_lines(job)):
        if line:
            text += f"\n{line}"

    if job.description:
        marked = highlight(_truncate(job.description, PLAIN_DESCRIPTION_LIMIT), PLAIN_MARKS)
        description_text = "\n".join(marked.splitlines())
        text += f"\nDescription:\n<blockquote expandable>{description_text}</blockquote>"

    return text
