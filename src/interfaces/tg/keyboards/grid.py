"""A grid of item buttons with pages — the one layout for every list the bot shows.

Docker projects, containers and VPN clients are all "a list of named things with a status";
one builder keeps them looking and paging the same way.
"""

from collections.abc import Callable
from math import ceil

from aiogram.types import InlineKeyboardButton

COLUMNS = 2
PER_PAGE = 10


def button_grid(
    buttons: list[InlineKeyboardButton],
    page: int = 0,
    page_callback: Callable[[int], str] | None = None,
    columns: int = COLUMNS,
    per_page: int = PER_PAGE,
) -> list[list[InlineKeyboardButton]]:
    """Rows of `columns` buttons; past `per_page` items, pages with ◀️ n/m ▶️ under them.

    `page_callback(page)` packs the callback data of a page switch; without it everything is
    shown on one page. An out-of-range page (the list shrank since the message was sent)
    snaps to the nearest one.
    """
    if page_callback is None or len(buttons) <= per_page:
        return [buttons[i : i + columns] for i in range(0, len(buttons), columns)]

    pages = ceil(len(buttons) / per_page)
    page = min(max(page, 0), pages - 1)
    shown = buttons[page * per_page : (page + 1) * per_page]
    rows = [shown[i : i + columns] for i in range(0, len(shown), columns)]
    rows.append(
        [
            InlineKeyboardButton(text="◀️", callback_data=page_callback((page - 1) % pages)),
            InlineKeyboardButton(text=f"{page + 1} / {pages}", callback_data=page_callback(page)),
            InlineKeyboardButton(text="▶️", callback_data=page_callback((page + 1) % pages)),
        ]
    )
    return rows
