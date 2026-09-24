from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import settings


class JobActionCallback(CallbackData, prefix="job"):
    action: str  # "apply" | "reject"
    job_id: str


def get_job_link_kb(link: str) -> InlineKeyboardMarkup:
    # Резервный вариант на случай, если save_jobs_to_db() не вернул job_id (БД недоступна) —
    # без него в сообщении вообще не было бы способа дойти до вакансии.
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Вакансия", url=link, style="primary")]])


# Djinni refuses an application that misses its experience gate; the same vacancy on another
# site often takes it. This button keeps the group open instead of closing it as "not interested".
BLOCKING_PLATFORMS = ("Djinni",)


def _link(job_id: str) -> str:
    return f"{settings.webhook_url}/jobs/r/{job_id}"


def get_job_action_kb(
    job_id: str, platform: str | None = None, copies: list[dict] | None = None
) -> InlineKeyboardMarkup:
    """The vacancy link, the same vacancy on other sites, and the owner's answer."""
    links = [InlineKeyboardButton(text="🔗 Вакансия", url=_link(job_id), style="primary")]
    links += [
        InlineKeyboardButton(text=f"🔗 {copy['platform']}", url=_link(copy["id"]))
        for copy in (copies or [])
        if copy.get("id") and copy.get("platform")
    ]
    rows = [links[i : i + 3] for i in range(0, len(links), 3)]
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Откликнулся",
                callback_data=JobActionCallback(action="apply", job_id=job_id).pack(),
                style="success",
            ),
            InlineKeyboardButton(
                text="❌ Не интересует",
                callback_data=JobActionCallback(action="reject", job_id=job_id).pack(),
                style="danger",
            ),
        ]
    )
    if platform in BLOCKING_PLATFORMS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"⛔ {platform} не пускает",
                    callback_data=JobActionCallback(action="block", job_id=job_id).pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
