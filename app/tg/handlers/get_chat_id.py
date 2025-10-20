from asyncio import sleep

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from aiogram.filters import Command

router = Router()


@router.message(Command("get_chat_id"))
async def get_chat_id_command(message: Message):
    await message.delete()

    chat = message.chat
    thread_id = message.message_thread_id or "❌ No thread"

    text = (
        f"📝 <b>Chat Info</b>\n"
        f"💬 <b>Type:</b> {chat.type}\n"
        f"🆔 <b>Chat ID:</b> <code>{chat.id}</code>\n"
        f"🧵 <b>Thread ID:</b> <code>{thread_id}</code>\n\n"
    )

    if chat.type in ["group", "supergroup"]:
        try:
            members_count = await message.bot.get_chat_member_count(chat.id)
            text += f"👥 <b>Members:</b> {members_count}\n"
        except TelegramBadRequest:
            text += "👥 <b>Members:</b> ❌ Cannot fetch\n"

    sent = await message.answer(text, disable_notification=True)
    await sleep(10)
    await sent.delete()
