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
from src.services.job_searcher.dedup import DECIDED, DUPLICATE, group_root

logger = logging.getLogger("tg.handlers.callbacks.job")

router = Router()
router.callback_query.middleware(AdminMiddleware())

_STATUS_INFO = {
    "apply": ("applied", "✅", "Откликнулся"),
    "reject": ("not_interested", "❌", "Не интересует"),
    "block": ("blocked", "⛔", "Не пускает — пришлю копию с другой площадки"),
}
_DECIDED_INFO = {status: (emoji, text) for status, emoji, text in _STATUS_INFO.values()}


async def _group_docs(root: str) -> list[dict]:
    query: dict = {"group_id": root}
    try:
        query = {"$or": [{"_id": ObjectId(root)}, {"group_id": root}]}
    except InvalidId:
        pass
    return [doc async for doc in jobs_collection.find(query)]


async def _edit(query: CallbackQuery, doc: dict, status: str) -> None:
    message = query.message
    if not isinstance(message, Message):
        return
    if message.rich_message is not None:
        # A rich message has no html_text to append to — render it again from the stored vacancy.
        await message.edit_text(
            rich_message=InputRichMessage(html=job_to_rich_html(Job.from_doc(doc), status=status)),
            reply_markup=None,
        )
    else:
        # Messages sent before rich formatting: keep the text, add the status line.
        await message.edit_text(f"{message.html_text}\n\n{status}", reply_markup=None, disable_web_page_preview=True)


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
        doc = await jobs_collection.find_one({"_id": job_object_id})
        if doc is None:
            await query.answer("Вакансия не найдена", show_alert=True)
            return
        group = await _group_docs(group_root(doc))
        # Another copy of this vacancy was answered already: one vacancy, one decision in the stats.
        answered = next(
            (d for d in group if d["_id"] != doc["_id"] and d.get("user_status") in DECIDED),
            None,
        )
        if answered is not None and user_status in DECIDED:
            user_status = DUPLICATE
            emoji, status_text = _DECIDED_INFO[answered["user_status"]]
            status_text = f"{status_text} (на {answered.get('platform_name')})"
        doc = await jobs_collection.find_one_and_update(
            {"_id": job_object_id},
            {"$set": {"user_status": user_status, "status_updated_at": datetime.utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        if user_status in DECIDED:
            # The copies still waiting in the chat are the same vacancy — they are answered too.
            await jobs_collection.update_many(
                {"_id": {"$in": [d["_id"] for d in group if d["_id"] != job_object_id]}, "user_status": "pending"},
                {"$set": {"user_status": DUPLICATE, "status_updated_at": datetime.utcnow()}},
            )
    except Exception as e:
        logger.warning("Failed to update job status in DB: %s", e)
        await query.answer("Не удалось обновить статус (БД недоступна)", show_alert=True)
        return

    if doc is None:
        await query.answer("Вакансия не найдена", show_alert=True)
        return

    await _edit(query, doc, job_status_html(emoji, status_text, datetime.now()))

    logger.info("Job %s marked as %s by user_id=%s", callback_data.job_id, user_status, query.from_user.id)
    await query.answer()
