"""/github — which repos the bot follows, how loudly, and into which forum topic. Admin only.

The repo list is the GitHub App's: every repo of the account, new ones included. A topic is bound by
`/bind [name]` sent inside it (the Bot API cannot list a forum's topics), created from here, or picked up
when someone creates or renames a topic in a forum the bot already writes to.
"""

import logging
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from src.config import settings
from src.interfaces.tg.formatters import github as fmt
from src.interfaces.tg.keyboards.github import GhLevel, GhNewTopic, GhOpen, GhRepo, GhSetTopic, list_kb, repo_kb
from src.interfaces.tg.middlewares.admin import AdminMiddleware
from src.services.github import store
from src.services.github.api import GithubApiError, GithubApp
from src.services.github.store import LEVELS, RepoConfig

logger = logging.getLogger("tg.handlers.admin.github")

router = Router()
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())
# In the forum itself: topic service messages come from whoever made the topic (only forums already in use are
# read), and /bind from anyone — the admin check is silent there, so the forum never sees a refusal.
topics_router = Router()

PAGE_SIZE = 10
# The App's repo list is read at most this often: paging through /github does not ask GitHub each time.
REPOS_TTL = 60.0

_app: GithubApp | None = None
_private: dict[str, bool] = {}
# Never fetched: -inf, not 0.0 — monotonic() starts near zero on a fresh boot, and 0.0 would read as
# a list fetched just now.
_names: tuple[float, list[str]] = (float("-inf"), [])
_page = 0  # the list page the owner came from: one admin, so module state is enough


def use_app(app: GithubApp) -> None:
    global _app
    _app = app


async def _repo_names() -> list[str]:
    global _names
    if time.monotonic() - _names[0] < REPOS_TTL:
        return _names[1]
    if _app is None or not _app.configured:
        return []
    try:
        found = await _app.repos()
    except GithubApiError as e:
        logger.warning("Repos of the App not listed: %s", e)
        return _names[1]
    _private.update({r.full_name: r.private for r in found})
    _names = (time.monotonic(), [r.full_name for r in found if not r.archived])
    return _names[1]


def _followed_first(cfg: RepoConfig) -> tuple[int, str]:
    """Repos with a topic first, then those still on, then the switched-off ones; by name inside."""
    rank = 0 if cfg.topic and cfg.level != "off" else 1 if cfg.level != "off" else 2
    return rank, cfg.full_name.lower()


async def _list_screen(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    global _page
    names = await _repo_names()
    repos = sorted(await store.sync_repos(names), key=_followed_first) if names else []
    pages = max(1, -(-len(repos) // PAGE_SIZE))
    _page = min(max(page, 0), pages - 1)
    shown = repos[_page * PAGE_SIZE : (_page + 1) * PAGE_SIZE]
    rows = [(cfg, _private.get(cfg.full_name, False)) for cfg in shown]
    has_forum = bool(await store.forum_chats())
    return fmt.admin_list(len(repos), _page, pages, has_forum), list_kb(rows, _page, pages)


async def _repo_screen(repo_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    cfg = await store.repo_by_id(repo_id)
    if cfg is None:
        return None
    private = _private.get(cfg.full_name, False)
    topics = await store.topics()
    return fmt.admin_repo(cfg, private), repo_kb(cfg, topics, can_create=bool(topics), back_page=_page)


async def _show(query: CallbackQuery, screen: tuple[str, InlineKeyboardMarkup] | None) -> None:
    if screen is None:
        await query.answer("Репо уже нет", show_alert=True)
        return
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(screen[0], reply_markup=screen[1], disable_web_page_preview=True)
        except TelegramAPIError as e:
            if "not modified" not in str(e).lower():
                await query.message.answer(screen[0], reply_markup=screen[1], disable_web_page_preview=True)
    await query.answer()


@router.message(Command("github"), F.chat.type == "private")
async def github_command(message: Message) -> None:
    text, keyboard = await _list_screen()
    await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


@router.callback_query(GhOpen.filter())
async def open_callback(query: CallbackQuery, callback_data: GhOpen) -> None:
    await _show(query, await _list_screen(callback_data.page))


@router.callback_query(GhRepo.filter())
async def repo_callback(query: CallbackQuery, callback_data: GhRepo) -> None:
    await _show(query, await _repo_screen(callback_data.repo_id))


@router.callback_query(GhLevel.filter(F.level.in_(LEVELS)))
async def level_callback(query: CallbackQuery, callback_data: GhLevel) -> None:
    await store.set_level(callback_data.repo_id, callback_data.level)  # type: ignore[arg-type]
    await _show(query, await _repo_screen(callback_data.repo_id))


@router.callback_query(GhSetTopic.filter())
async def topic_callback(query: CallbackQuery, callback_data: GhSetTopic) -> None:
    topic_id = callback_data.topic_id or None
    if topic_id is not None and await store.topic(topic_id) is None:
        await query.answer("Темы уже нет", show_alert=True)
        return
    await store.set_topic(callback_data.repo_id, topic_id)
    await _show(query, await _repo_screen(callback_data.repo_id))


@router.callback_query(GhNewTopic.filter())
async def new_topic_callback(query: CallbackQuery, callback_data: GhNewTopic, bot: Bot) -> None:
    cfg = await store.repo_by_id(callback_data.repo_id)
    chats = sorted(await store.forum_chats())
    if cfg is None or not chats:
        await query.answer("Сначала привяжи форум: /bind в любой его теме", show_alert=True)
        return
    name = fmt.short(cfg.full_name)
    try:
        created = await bot.create_forum_topic(chats[0], name)
    except TelegramAPIError as e:
        logger.warning("Topic %s not created: %s", name, e)
        await query.answer("Telegram не дал создать тему: у бота есть право «Управление темами»?", show_alert=True)
        return
    topic = await store.save_topic(chats[0], created.message_thread_id, name)
    await store.set_topic(cfg.id, topic.id)
    await _show(query, await _repo_screen(cfg.id))


@topics_router.message(Command("bind"), F.is_topic_message)
async def bind_command(message: Message, command: CommandObject) -> None:
    """`/bind [name]` inside a forum topic: the bot will offer it in /github. The command is removed."""
    if message.from_user is None or message.from_user.id != settings.telegram_admin_id:
        return
    assert message.message_thread_id is not None
    created = message.reply_to_message.forum_topic_created if message.reply_to_message else None
    name = (command.args or "").strip()[:128] or (created.name if created else None)
    topic = await store.save_topic(message.chat.id, message.message_thread_id, name)
    try:
        await message.delete()
    except TelegramAPIError:
        pass
    if message.bot is not None:
        await message.bot.send_message(message.from_user.id, fmt.topic_bound(topic))


@topics_router.message(F.forum_topic_created | F.forum_topic_edited)
async def topic_seen(message: Message) -> None:
    if message.chat.id not in await store.forum_chats() or message.message_thread_id is None:
        return
    if message.forum_topic_created:
        await store.save_topic(message.chat.id, message.message_thread_id, message.forum_topic_created.name)
    elif message.forum_topic_edited and message.forum_topic_edited.name:
        await store.save_topic(message.chat.id, message.message_thread_id, message.forum_topic_edited.name)
