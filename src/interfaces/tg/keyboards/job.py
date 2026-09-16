from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import settings


class JobActionCallback(CallbackData, prefix="job"):
    action: str  # "apply" | "reject"
    job_id: str


def get_job_link_kb(link: str) -> InlineKeyboardMarkup:
    # Резервный вариант на случай, если save_jobs_to_db() не вернул job_id (БД недоступна) —
    # без него в сообщении вообще не было бы способа дойти до вакансии.
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Вакансия", url=link)]])


def get_job_action_kb(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Вакансия", url=f"{settings.webhook_url}/jobs/r/{job_id}")],
            [
                InlineKeyboardButton(
                    text="✅ Откликнулся",
                    callback_data=JobActionCallback(action="apply", job_id=job_id).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Не интересует",
                    callback_data=JobActionCallback(action="reject", job_id=job_id).pack(),
                ),
            ],
        ]
    )
