import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InputRichMessage, Message

logger = logging.getLogger("tg.rich")


async def show_rich(message: Message, html: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    """Replace a screen in place; a message that cannot become rich is answered anew."""
    try:
        await message.edit_text(rich_message=InputRichMessage(html=html), reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            return  # "Обновить" with nothing changed
        logger.info("Could not edit the screen in place (%s), sending a new one", e)
        await message.answer_rich(rich_message=InputRichMessage(html=html), reply_markup=keyboard)


async def answer_rich(message: Message, html: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    await message.answer_rich(rich_message=InputRichMessage(html=html), reply_markup=keyboard)
