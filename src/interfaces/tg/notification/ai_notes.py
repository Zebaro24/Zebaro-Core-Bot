"""The AI's status changes as one message per session (16.11.2026), not a note per vacancy.

An AI sorting the inbox changed twenty vacancies in a row and twenty notes arrived. Now a quiet
change (anything but a reply, an interview or an offer — those still come on their own, loud)
goes into the session's message: the same message is edited while changes keep coming less than
SESSION apart, up to NOTES_PER_MESSAGE of them (Telegram's 4096 characters). "↩️ Отменить…"
under it asks which one to take back.

State in `meta`: `ai_notes:current` points at the open message; `ai_notes:<message id>` holds its
entries (vacancy id, event id). The message is rendered from the vacancies' history, so an undo
shows up on the next render whoever made it.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from src.config import settings
from src.db import sql
from src.interfaces.tg.formatters.job_status import ai_notes_html
from src.interfaces.tg.keyboards.job import get_notes_kb, get_notes_pick_kb
from src.services.job_searcher import store
from src.services.job_searcher.jobs_api import public_status
from src.services.job_searcher.models import AiNoteMessage

logger = logging.getLogger("tg.notification.ai_notes")

SESSION = timedelta(minutes=30)
NOTES_PER_MESSAGE = 12
MAX_TEXT = 3800  # Telegram's limit is 4096; a few long LinkedIn entries reach it before twelve
CURRENT = "ai_notes:current"
# The sync loop adds, a button press renders: one at a time, or a render from older state undoes an add.
_lock = asyncio.Lock()


async def _state(message_id: int) -> dict[str, Any] | None:
    """The message's chat and entries, None when the bot does not know the message."""
    async with sql.session() as s:
        row = await s.get(AiNoteMessage, message_id)
        return {"chat_id": row.chat_id, "entries": list(row.entries)} if row is not None else None


async def add_note(bot: Bot, doc: dict[str, Any], event: dict[str, Any]) -> None:
    """Put one change into the session's message. Telegram errors go to the caller (the sync
    loop retries); a retry finds the entry already there and only renders again."""
    async with _lock:
        now = datetime.utcnow()
        entry = {"job_id": str(doc["_id"]), "event_id": event["id"]}
        current = await sql.kv_get(CURRENT)
        if current and now - current["last_at"] < SESSION:
            message_id = current["message_id"]
            state = await _state(message_id)
            entries = state["entries"] if state else []
            known = any(item["event_id"] == entry["event_id"] for item in entries)
            if state and (known or len(entries) < NOTES_PER_MESSAGE):
                entries = entries if known else [*entries, entry]
                text, open_entries = await _render(entries)
                if known or len(text) <= MAX_TEXT:  # past it Telegram refuses the edit: a new message
                    # Saved first: an undo rendering the message meanwhile must not drop this entry.
                    await _save(message_id, state["chat_id"], entries, now)
                    if await _edit(bot, state["chat_id"], message_id, text, open_entries):
                        return
        text, open_entries = await _render([entry])
        message = await bot.send_message(
            chat_id=settings.telegram_admin_id,
            text=text,
            reply_markup=get_notes_kb(len(open_entries)),
            disable_notification=True,
            disable_web_page_preview=True,
        )
        try:
            await _save(message.message_id, message.chat.id, [entry], now)
        except sql.UNAVAILABLE as e:  # sent already: a retry would send it twice; the next note starts anew
            logger.warning("AI notes: could not store the new message %s: %s", message.message_id, e)


async def refresh(bot: Bot, chat_id: int, message_id: int, *, picking: bool = False) -> bool:
    """Render the message again (after an undo, or to show / hide the choice). False when it
    is not an AI notes message the bot knows."""
    async with _lock:
        state = await _state(message_id)
        if state is None:
            return False
        text, open_entries = await _render(state["entries"])
        await _edit(bot, chat_id, message_id, text, open_entries, picking=picking)
        return True


async def _save(message_id: int, chat_id: int, entries: list[dict[str, str]], now: datetime) -> None:
    async with sql.session() as s:
        row = await s.get(AiNoteMessage, message_id, with_for_update=True)
        if row is None:
            s.add(AiNoteMessage(message_id=message_id, chat_id=chat_id, entries=list(entries)))
        else:
            row.chat_id, row.entries = chat_id, list(entries)
        await s.commit()
    await sql.kv_merge(CURRENT, {"message_id": message_id, "last_at": now})


async def _render(entries: list[dict[str, str]]) -> tuple[str, list[tuple[int, str, str, str]]]:
    """The text, and the entries that can still be undone: (number, name, vacancy id, event id)."""
    ids = [item["job_id"] for item in entries]
    docs = {doc["_id"]: doc for doc in await store.find(store.J.id.in_(ids), description=False)}
    items, open_entries = [], []
    for item in entries:
        doc = docs.get(item["job_id"])
        history = (doc or {}).get("history") or []
        event = next((e for e in history if e.get("id") == item["event_id"]), None)
        if doc is None or event is None:
            continue
        undone = any(e.get("undo_of") == item["event_id"] for e in history)
        items.append((doc, event, undone))
        # Only the vacancy's last change can be undone, and only while its status is still that one.
        if not undone and history[-1].get("id") == item["event_id"] and public_status(doc) == event.get("to"):
            name = doc.get("company") or doc.get("title") or "?"
            open_entries.append((len(items), name, item["job_id"], item["event_id"]))
    return ai_notes_html(items), open_entries


async def _edit(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    open_entries: list[tuple[int, str, str, str]],
    *,
    picking: bool = False,
) -> bool:
    """False when the message is gone: the caller starts a new one."""
    markup = get_notes_pick_kb(open_entries) if picking and open_entries else get_notes_kb(len(open_entries))
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        reason = str(e).lower()
        if "not modified" in reason:
            return True
        if "message to edit not found" in reason or "message can't be edited" in reason:
            logger.info("AI notes: the message %s is gone (%s)", message_id, e)
            return False
        raise
    return True
