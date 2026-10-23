import logging
from datetime import datetime

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputRichMessage, Message
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from src.db.client import jobs_collection
from src.interfaces.tg.formatters.job import job_status_html, job_to_html, job_to_rich_html
from src.interfaces.tg.keyboards.job import (
    OUTCOME_TEXTS,
    REASON_TEXTS,
    JobActionCallback,
    LegacyJobCallback,
    get_job_action_kb,
    get_job_outcome_kb,
    get_job_reason_kb,
)
from src.interfaces.tg.middlewares.admin import AdminMiddleware
from src.services.job_searcher.container import Job
from src.services.job_searcher.dedup import BLOCKED, DECIDED, DUPLICATE, group_root

logger = logging.getLogger("tg.handlers.callbacks.job")

router = Router()
router.callback_query.middleware(AdminMiddleware())

# The stored status, its emoji and its words.
_STATUS_INFO = {
    "applied": ("✅", "Откликнулся"),
    "mismatch": ("🚫", "Не прохожу"),
    "not_interested": ("👎", "Не интересно"),
    BLOCKED: ("⛔", "Сайт не пускает — пришлю копию с другой площадки"),
}
# Messages sent before the reasons (06.10.2026) still carry these answers.
_LEGACY_ACTIONS = {"block": (BLOCKED, "site")}
_REASON_MENUS = ("mismatch", "reject")


async def _group_docs(root: str) -> list[dict]:
    query: dict = {"group_id": root}
    try:
        query = {"$or": [{"_id": ObjectId(root)}, {"group_id": root}]}
    except InvalidId:
        pass
    return [doc async for doc in jobs_collection.find(query)]


async def _edit(query: CallbackQuery, doc: dict, status: str, markup: InlineKeyboardMarkup | None = None) -> None:
    message = query.message
    if not isinstance(message, Message):
        return
    try:
        if message.rich_message is not None:
            # A rich message has no html_text to append to — render it again from the stored vacancy.
            await message.edit_text(
                rich_message=InputRichMessage(html=job_to_rich_html(Job.from_doc(doc), status=status)),
                reply_markup=markup,
            )
        else:
            # Messages sent before rich formatting: keep the text, add the status line.
            await message.edit_text(
                f"{message.html_text}\n\n{status}", reply_markup=markup, disable_web_page_preview=True
            )
    except TelegramBadRequest as e:
        # The same outcome pressed twice within a minute renders the very same message.
        if "not modified" not in str(e):
            raise


def _applied_status(doc: dict) -> str:
    """ "✅ Откликнулся · 🗓 Интервью — <now>": the application and how far it went."""
    text = _STATUS_INFO["applied"][1]
    if outcome := doc.get("outcome"):
        text = f"{text} · {OUTCOME_TEXTS.get(outcome, outcome)}"
    return job_status_html(_STATUS_INFO["applied"][0], text, datetime.now())


async def _record_outcome(query: CallbackQuery, callback_data: JobActionCallback) -> None:
    if callback_data.reason not in OUTCOME_TEXTS:
        await query.answer("Неизвестный исход")
        return
    try:
        doc = await jobs_collection.find_one_and_update(
            {"_id": ObjectId(callback_data.job_id), "user_status": "applied"},
            {"$set": {"outcome": callback_data.reason, "outcome_at": datetime.utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
    except Exception as e:  # a bad id and a DB outage end the same way
        logger.warning("Failed to store the outcome: %s", e)
        await query.answer("Не удалось сохранить (БД недоступна)", show_alert=True)
        return
    if doc is None:
        await query.answer("Отклик не найден", show_alert=True)
        return
    markup = get_job_outcome_kb(callback_data.job_id, doc.get("copies"), current=callback_data.reason)
    await _edit(query, doc, _applied_status(doc), markup)
    logger.info("Job %s outcome: %s", callback_data.job_id, callback_data.reason)
    await query.answer()


async def _open_from_summary(query: CallbackQuery, callback_data: JobActionCallback) -> None:
    """A vacancy of the 👀 summary as its own message, with the usual buttons."""
    try:
        doc = await jobs_collection.find_one({"_id": ObjectId(callback_data.job_id)})
    except Exception as e:
        logger.warning("Could not read the vacancy to open it: %s", e)
        doc = None
    if doc is None or not isinstance(query.message, Message):
        await query.answer("Вакансия не найдена", show_alert=True)
        return
    status = doc.get("user_status")
    if status == "applied":
        text, markup = (
            _applied_status(doc),
            get_job_outcome_kb(callback_data.job_id, doc.get("copies"), doc.get("outcome")),
        )
    elif status in _STATUS_INFO or status == DUPLICATE:
        emoji, words = _STATUS_INFO.get(status, ("✔️", "Уже решено"))
        text, markup = f"{emoji} <b>{words}</b>", None
    else:
        text, markup = None, get_job_action_kb(callback_data.job_id, doc.get("copies"))
    job = Job.from_doc(doc)
    try:
        await query.message.answer_rich(
            rich_message=InputRichMessage(html=job_to_rich_html(job, status=text)), reply_markup=markup
        )
    except TelegramBadRequest:
        # As when the run sent it: a refused rich message falls back to plain HTML.
        logger.warning("Telegram refused the rich message for %s, sending the plain version", job, exc_info=True)
        plain = f"{job_to_html(job)}\n\n{text}" if text else job_to_html(job)
        await query.message.answer(plain, reply_markup=markup, disable_web_page_preview=True)
    await query.answer()


def _answer(callback_data: JobActionCallback) -> tuple[str, str | None] | None:
    """The status and the reason a button stands for; None for a button that only opens a menu."""
    if callback_data.action in _LEGACY_ACTIONS:
        return _LEGACY_ACTIONS[callback_data.action]
    if callback_data.action == "apply":
        return "applied", None
    if callback_data.action in _REASON_MENUS and callback_data.reason:
        if callback_data.action == "mismatch":
            # "The site will not let me" keeps its own status: dedup sends a copy from elsewhere.
            return (BLOCKED if callback_data.reason == "site" else "mismatch"), callback_data.reason
        return "not_interested", callback_data.reason
    return None


async def _switch_buttons(query: CallbackQuery, callback_data: JobActionCallback) -> None:
    """Open the reasons of a "no", or go back to the main buttons — the same message."""
    message = query.message
    if not isinstance(message, Message):
        return
    try:
        doc = await jobs_collection.find_one({"_id": ObjectId(callback_data.job_id)})
    except Exception as e:  # a bad id and a DB outage end the same way: buttons without copies
        logger.warning("Could not read the vacancy for its buttons: %s", e)
        doc = None
    copies = (doc or {}).get("copies") or []
    if callback_data.action == "back":
        markup = get_job_action_kb(callback_data.job_id, copies)
    else:
        markup = get_job_reason_kb(callback_data.job_id, callback_data.action, copies)
    await message.edit_reply_markup(reply_markup=markup)


@router.callback_query(LegacyJobCallback.filter())
async def legacy_job_action_callback(query: CallbackQuery, callback_data: LegacyJobCallback) -> None:
    """An old message's button: "apply" and "block" answer as before, "reject" opens the reasons."""
    await job_action_callback(query, JobActionCallback(action=callback_data.action, job_id=callback_data.job_id))


@router.callback_query(JobActionCallback.filter())
async def job_action_callback(query: CallbackQuery, callback_data: JobActionCallback) -> None:
    if not isinstance(query.message, Message):
        await query.answer()
        return
    if callback_data.action == "outcome":
        await _record_outcome(query, callback_data)
        return
    if callback_data.action == "open":
        await _open_from_summary(query, callback_data)
        return

    answer = _answer(callback_data)
    if answer is None:
        if callback_data.action in (*_REASON_MENUS, "back"):
            await _switch_buttons(query, callback_data)
            await query.answer()
        else:
            await query.answer("Неизвестное действие")
        return

    user_status, reason = answer
    emoji, status_text = _STATUS_INFO[user_status]
    if reason and user_status != BLOCKED:
        menu = "mismatch" if user_status == "mismatch" else "reject"
        label = REASON_TEXTS[menu].get(reason, f" {reason}")  # a renamed reason must not crash an old button
        status_text = f"{status_text}: {label.split(' ', 1)[-1].lower()}"

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
            emoji, status_text = _STATUS_INFO.get(answered["user_status"], ("✔️", "Уже решено"))
            status_text = f"{status_text} (на {answered.get('platform_name')})"
        doc = await jobs_collection.find_one_and_update(
            {"_id": job_object_id},
            {"$set": {"user_status": user_status, "status_reason": reason, "status_updated_at": datetime.utcnow()}},
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

    # An application keeps its buttons: what came of it is pressed later on the same message.
    markup = get_job_outcome_kb(callback_data.job_id, doc.get("copies")) if user_status == "applied" else None
    await _edit(query, doc, job_status_html(emoji, status_text, datetime.now()), markup)

    logger.info("Job %s marked as %s (%s) by user_id=%s", callback_data.job_id, user_status, reason, query.from_user.id)
    await query.answer()
