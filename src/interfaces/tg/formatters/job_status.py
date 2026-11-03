"""A vacancy's status in Telegram: the line in its message and the note about a change.

The words match the buttons (keyboards/job.py): a status set through the API looks the same as
one pressed, plus 🤖 when the AI set it.
"""

import html
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.config import settings
from src.interfaces.tg.formatters.job import job_status_html
from src.interfaces.tg.keyboards.job import OUTCOME_TEXTS, REASON_TEXTS
from src.services.job_searcher.jobs_api import public_status
from src.services.job_searcher.reasons import EMPLOYER_LABELS

_OUTCOME_OF = {"replied": "reply", "interview": "interview", "offer": "offer", "rejected_by_employer": "rejected"}
# Short names for "from → to".
STATUS_NAMES = {
    "new": "Без решения",
    "applied": "Откликнулся",
    "replied": "Ответили",
    "interview": "Интервью",
    "offer": "Оффер",
    "rejected_by_employer": "Отказ",
    "mismatch": "Не прохожу",
    "not_interested": "Не интересно",
    "blocked": "Сайт не пускает",
    "duplicate": "Повтор",
}
_ACTORS = {"ai": "🤖 AI", "user": "👤 Ты", "system": "⚙️ Бот"}


def reason_label(status: str, code: str | None) -> str | None:
    """ "зарплата", "опыт / уровень": a code in the words of its button."""
    if not code:
        return None
    if status == "rejected_by_employer":
        return EMPLOYER_LABELS.get(code, code)
    menu = {"mismatch": "mismatch", "not_interested": "reject"}.get(status)
    if menu is None:
        return None
    label = REASON_TEXTS[menu].get(code)
    return label.split(" ", 1)[-1].lower() if label else code


def status_words(status: str, reason_code: str | None = None) -> tuple[str, str] | None:
    """(emoji, words) for a status; None for "new" — such a message shows its buttons instead."""
    if status == "new":
        return None
    label = reason_label(status, reason_code)
    if status == "applied" or status in _OUTCOME_OF:
        text = "Откликнулся"
        if status in _OUTCOME_OF:
            text = f"{text} · {OUTCOME_TEXTS[_OUTCOME_OF[status]]}"
        return "✅", f"{text}: {label}" if label else text
    if status == "mismatch":
        return "🚫", f"Не прохожу: {label}" if label else "Не прохожу"
    if status == "not_interested":
        return "👎", f"Не интересно: {label}" if label else "Не интересно"
    if status == "blocked":
        return "⛔", "Сайт не пускает — пришлю копию с другой площадки"
    return "✔️", "Уже решено"


def local_time(moment: datetime) -> datetime:
    """A stored (naive UTC) time on the owner's clock."""
    return moment.replace(tzinfo=UTC).astimezone(ZoneInfo(settings.tz))


def job_status_line(doc: dict[str, Any]) -> str | None:
    """The status line of a vacancy's message, from the stored document; 🤖 when the AI set it."""
    words = status_words(public_status(doc), doc.get("status_reason"))
    if words is None:
        return None
    emoji, text = words
    history = doc.get("history") or []
    last = history[-1] if history else {}
    if last.get("actor") == "ai":
        emoji = f"🤖 {emoji}"
    when = last.get("occurred_at") or doc.get("outcome_at") or doc.get("status_updated_at")
    return job_status_html(emoji, text, local_time(when) if isinstance(when, datetime) else datetime.now())


def status_change_html(doc: dict[str, Any], event: dict[str, Any]) -> str:
    """The note under a vacancy: who changed what, why and on what evidence."""
    to, frm = event.get("to") or "new", event.get("from") or "new"
    name = STATUS_NAMES.get(to, to)
    label = reason_label(to, event.get("reason_code"))
    if event.get("reason_code") == "other" and event.get("suggested_code"):
        label = f"другое — {event['suggested_code']}"
    head = f"{_ACTORS.get(event.get('actor') or '', '⚙️ Бот')}: {STATUS_NAMES.get(frm, frm)} → <b>{name}</b>"
    lines = [f"{head} ({html.escape(label)})" if label else head]
    vacancy = html.escape(doc.get("title") or "Без названия")
    lines.append(f"<b>{html.escape(doc['company'])}</b> — {vacancy}" if doc.get("company") else vacancy)
    if event.get("reason"):
        lines.append(f"<i>{html.escape(event['reason'])}</i>")
    return "\n".join(lines)
