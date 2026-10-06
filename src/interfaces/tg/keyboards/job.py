from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import settings


class JobActionCallback(CallbackData, prefix="job"):
    # "apply" | "mismatch" / "reject" (with a reason: the answer; without: open the reasons) |
    # "back" (the reasons → the main buttons) | "block" (old messages: "the site will not let me")
    action: str
    job_id: str
    reason: str = ""


class LegacyJobCallback(CallbackData, prefix="job"):
    """Buttons of messages sent before the reasons (06.10.2026): "job:apply|reject|block:<id>".

    The reason field made the new class expect three parts, and aiogram's filter silently
    drops data with two — every vacancy already in the chat would have stopped answering.
    """

    action: str
    job_id: str


# Two different "no"s (06.10.2026): "I do not meet the requirements" is the filter's mistake —
# it tunes the parsers; "not interested" is taste — it tunes the scoring. The reason is one tap
# more, in the same message.
MISMATCH_REASONS = (
    ("experience", "🎓 Опыт / уровень"),
    ("location", "📍 Офис / страна"),
    ("english", "🗣 Английский"),
    ("stack", "🧰 Не знаю стек"),
    # The site refused the application (Djinni checks the profile): the group stays open and a
    # copy from another site is still sent.
    ("site", "⛔ Сайт не пускает"),
    ("other", "🤷 Другое"),
)
REJECT_REASONS = (
    ("role", "🎯 Не та роль"),
    ("stack", "🧰 Не тот стек"),
    ("domain", "🏭 Домен / компания"),
    ("conditions", "💸 Условия"),
    ("other", "🤷 Просто нет"),
)
REASON_TEXTS = {
    "mismatch": dict(MISMATCH_REASONS),
    "reject": dict(REJECT_REASONS),
}


def get_job_link_kb(link: str) -> InlineKeyboardMarkup:
    # Резервный вариант на случай, если save_jobs_to_db() не вернул job_id (БД недоступна) —
    # без него в сообщении вообще не было бы способа дойти до вакансии.
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Вакансия", url=link, style="primary")]])


def _link(job_id: str) -> str:
    return f"{settings.webhook_url}/jobs/r/{job_id}"


def _link_rows(job_id: str, copies: list[dict] | None) -> list[list[InlineKeyboardButton]]:
    links = [InlineKeyboardButton(text="🔗 Вакансия", url=_link(job_id), style="primary")]
    links += [
        InlineKeyboardButton(text=f"🔗 {copy['platform']}", url=_link(copy["id"]))
        for copy in (copies or [])
        if copy.get("id") and copy.get("platform")
    ]
    return [links[i : i + 3] for i in range(0, len(links), 3)]


def _button(text: str, action: str, job_id: str, reason: str = "", style: str | None = None) -> InlineKeyboardButton:
    data = JobActionCallback(action=action, job_id=job_id, reason=reason).pack()
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def get_job_action_kb(job_id: str, copies: list[dict] | None = None) -> InlineKeyboardMarkup:
    """The vacancy link, the same vacancy on other sites, and the owner's answer."""
    rows = _link_rows(job_id, copies)
    rows.append([_button("✅ Откликнулся", "apply", job_id, style="success")])
    rows.append(
        [
            _button("🚫 Не прохожу", "mismatch", job_id, style="danger"),
            _button("👎 Не интересно", "reject", job_id),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_job_reason_kb(job_id: str, action: str, copies: list[dict] | None = None) -> InlineKeyboardMarkup:
    """The reasons for one "no", two per row, under the same links."""
    reasons = MISMATCH_REASONS if action == "mismatch" else REJECT_REASONS
    buttons = [_button(text, action, job_id, reason) for reason, text in reasons]
    rows = _link_rows(job_id, copies) + [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([_button("↩️ Назад", "back", job_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
