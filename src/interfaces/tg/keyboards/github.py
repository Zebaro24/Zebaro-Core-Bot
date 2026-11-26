"""GitHub buttons. Only in the owner's chat: the forum gets plain links, since everyone there sees buttons.

Callback data is at most 64 bytes, so repos travel as their SQL id, and "Перезапустить" carries nothing —
the run is the one recorded for the message the button sits on.
"""

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.interfaces.tg.formatters.github import LEVEL_LABEL, repo_button
from src.services.github.store import LEVELS, RepoConfig, Topic


class GhRerun(CallbackData, prefix="ghrr"):
    pass


class GhRecreate(CallbackData, prefix="ghtr"):
    topic_id: int


class GhOpen(CallbackData, prefix="ghop"):
    pass


class GhRepo(CallbackData, prefix="ghr"):
    repo_id: int


class GhLevel(CallbackData, prefix="ghl"):
    repo_id: int
    level: str


class GhSetTopic(CallbackData, prefix="ghst"):
    repo_id: int
    topic_id: int  # 0 — no topic


class GhNewTopic(CallbackData, prefix="ghnt"):
    repo_id: int


def failed_kb(url: str) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text="🔁 Перезапустить", callback_data=GhRerun().pack())]
    if url:
        row.insert(0, InlineKeyboardButton(text="Логи", url=url))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def open_kb(url: str) -> InlineKeyboardMarkup | None:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть", url=url)]]) if url else None


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⚙️ Настроить", callback_data=GhOpen().pack())]]
    )


def broken_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Создать заново", callback_data=GhRecreate(topic_id=topic_id).pack()),
                InlineKeyboardButton(text="Выбрать другую", callback_data=GhOpen().pack()),
            ]
        ]
    )


def list_kb(repos: list[tuple[RepoConfig, bool]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cfg, private in repos:
        builder.button(text=repo_button(cfg, private), callback_data=GhRepo(repo_id=cfg.id))
    builder.adjust(1)
    return builder.as_markup()


def repo_kb(cfg: RepoConfig, topics: list[Topic], can_create: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for level in LEVELS:
        mark = "• " if cfg.level == level else ""
        builder.button(text=mark + LEVEL_LABEL[level], callback_data=GhLevel(repo_id=cfg.id, level=level))
    current = cfg.topic.id if cfg.topic else 0
    for topic in topics:
        mark = "✓ " if topic.id == current else ""
        builder.button(text=f"{mark}# {topic.name}", callback_data=GhSetTopic(repo_id=cfg.id, topic_id=topic.id))
    builder.button(
        text=("✓ " if not current else "") + "Без темы", callback_data=GhSetTopic(repo_id=cfg.id, topic_id=0)
    )
    if can_create:
        builder.button(text="➕ Новая тема с именем репо", callback_data=GhNewTopic(repo_id=cfg.id))
    builder.button(text="← Все репо", callback_data=GhOpen())
    builder.adjust(len(LEVELS), *([1] * (len(topics) + 3)))
    return builder.as_markup()
