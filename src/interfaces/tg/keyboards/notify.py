from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class NotifyCallback(CallbackData, prefix="notify"):
    action: str = "seen"


def get_notify_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✓", callback_data=NotifyCallback().pack())]]
    )
