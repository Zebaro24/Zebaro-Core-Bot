import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_HANDLE = re.compile(r"^@([A-Za-z0-9_]{4,32})$")


def get_site_contact_kb(reply: str) -> InlineKeyboardMarkup | None:
    """A reply button for a Telegram handle or a link.

    Telegram buttons take only http(s) and tg links, not mailto: — an e-mail or a phone
    number becomes clickable in the message text on its own.
    """
    reply = reply.strip()
    if match := _HANDLE.match(reply):
        url = f"https://t.me/{match.group(1)}"
    elif reply.startswith(("https://", "http://")):
        url = reply
    else:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить", url=url, style="primary")]])
