import logging
from datetime import datetime

from aiogram import Router
from aiogram.types import CallbackQuery, InputRichMessage, Message
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from src.db.client import jobs_collection
from src.interfaces.tg.formatters.job import job_status_html, job_to_rich_html
from src.interfaces.tg.keyboards.job import JobActionCallback
from src.interfaces.tg.middlewares.admin import AdminMiddleware
from src.services.job_searcher.container import Job

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

    try:
        doc = await jobs_collection.find_one_and_update(
            {"_id": job_object_id},
            {"$set": {"user_status": user_status, "status_updated_at": datetime.utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
    except Exception as e:
        logger.warning("Failed to update job status in DB: %s", e)
        await query.answer("Не удалось обновить статус (БД недоступна)", show_alert=True)
        return

    if doc is None:
        await query.answer("Вакансия не найдена", show_alert=True)
        return

    status = job_status_html(emoji, status_text, datetime.now())
    if query.message.rich_message is not None:
        # A rich message has no html_text to append to — render it again from the stored vacancy.
        await query.message.edit_text(
            rich_message=InputRichMessage(html=job_to_rich_html(Job.from_doc(doc), status=status)),
            reply_markup=None,
        )
    else:
        # Messages sent before rich formatting: keep the text, add the status line.
        await query.message.edit_text(
            f"{query.message.html_text}\n\n{status}", reply_markup=None, disable_web_page_preview=True
        )

    logger.info("Job %s marked as %s by user_id=%s", callback_data.job_id, user_status, query.from_user.id)
    await query.answer()
