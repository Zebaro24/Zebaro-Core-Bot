import logging
from datetime import datetime

from aiogram import Router
from aiogram.types import CallbackQuery, Message
from bson import ObjectId
from bson.errors import InvalidId

from src.db.client import jobs_collection
from src.interfaces.tg.keyboards.job import JobActionCallback
from src.interfaces.tg.middlewares.admin import AdminMiddleware

logger = logging.getLogger("tg.handlers.callbacks.job")

router = Router()
router.callback_query.middleware(AdminMiddleware())

_STATUS_INFO = {
    "apply": ("applied", "✅", "Откликнулся"),
    "reject": ("not_interested", "❌", "Не интересует"),
}


@router.callback_query(JobActionCallback.filter())
async def job_action_callback(query: CallbackQuery, callback_data: JobActionCallback) -> None:
    if not isinstance(query.message, Message):
        await query.answer()
        return

    status_info = _STATUS_INFO.get(callback_data.action)
    if status_info is None:
        await query.answer("Неизвестное действие")
        return

    user_status, emoji, status_text = status_info

    try:
        job_object_id = ObjectId(callback_data.job_id)
    except InvalidId:
        await query.answer("Некорректный ID вакансии", show_alert=True)
        return

    status_updated_at = datetime.utcnow()
    try:
        result = await jobs_collection.update_one(
            {"_id": job_object_id},
            {"$set": {"user_status": user_status, "status_updated_at": status_updated_at}},
        )
    except Exception as e:
        logger.warning("Failed to update job status in DB: %s", e)
        await query.answer("Не удалось обновить статус (БД недоступна)", show_alert=True)
        return

    if result.matched_count == 0:
        await query.answer("Вакансия не найдена", show_alert=True)
        return

    date_str = status_updated_at.strftime("%d.%m.%Y %H:%M")
    new_text = f"{query.message.html_text}\n\n{emoji} <b>Статус:</b> {status_text} — {date_str}"
    await query.message.edit_text(new_text, reply_markup=None, disable_web_page_preview=True)

    logger.info("Job %s marked as %s by user_id=%s", callback_data.job_id, user_status, query.from_user.id)
    await query.answer()
