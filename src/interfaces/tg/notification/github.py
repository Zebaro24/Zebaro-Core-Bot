"""GitHub events in Telegram: the forum is a quiet log, the owner's chat gets only what needs them.

Forum (the repo's topic; several repos may share one): one message per commit and one per release, edited
as the workflows run — never a notification, never a button (everyone there would see it). Nothing goes
there for a repo without a topic, or one at "off"; at "fails" only what failed.
Owner's chat, loud, with buttons: a failed workflow on the main branch or a release, someone else's issue
or PR, a security alert, a forum topic that stopped working. A failure that turns green again is edited
into "снова зелёный" and removed an hour later.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from src.config import settings
from src.interfaces.tg.formatters import github as fmt
from src.interfaces.tg.keyboards.github import GhRecreate, GhRerun, broken_kb, failed_kb, open_kb, settings_kb
from src.interfaces.tg.middlewares.admin import AdminMiddleware
from src.services.github import store
from src.services.github.api import GithubApiError, GithubApp
from src.services.github.events import Alert, Event, NewRepos, Outside, Push, Release, Run, critical
from src.services.github.store import Live, RepoConfig, Topic

logger = logging.getLogger("tg.notification.github")

router = Router()
router.callback_query.middleware(AdminMiddleware())

FIXED_KEEP = 3600
SWEEP_MINUTES = 30
SWEEP_JOB_ID = "github_sweep"
# Someone else's issues and PRs: at most this many loud messages per repo an hour; the rest go to the forum only.
OUTSIDE_LIMIT = 5
OUTSIDE_WINDOW = 3600.0
# One wait for Telegram's flood control, at most this long; longer — the message is dropped and logged.
RETRY_AFTER_MAX = 30
_locks: dict[str, asyncio.Lock] = {}
_broken: set[int] = set()
_outside: dict[str, deque[float]] = {}


def make_deliver(bot: Bot, app: GithubApp) -> Callable[[Event], Awaitable[None]]:
    async def deliver(event: Event) -> None:
        await handle(bot, app, event)

    return deliver


async def handle(bot: Bot, app: GithubApp, event: Event) -> None:
    if isinstance(event, NewRepos):
        for name in event.names:
            await store.repo(name)
        await _owner(bot, fmt.new_repos(event), settings_kb(), loud=False)
        return
    cfg = await store.repo(event.repo)
    if cfg.level == "off":
        return
    if isinstance(event, Push):
        await _live_forum(bot, cfg, f"sha:{event.repo}:{event.sha}", _push_state(event), show=cfg.level == "all")
    elif isinstance(event, Run):
        await _run(bot, app, cfg, event)
    elif isinstance(event, Release):
        key = f"tag:{event.repo}:{event.tag}"
        update = {"repo": event.repo, "tag": event.tag, "notes": event.notes, "release_url": event.url}
        await _live_forum(bot, cfg, key, update, show=cfg.level == "all")
    elif isinstance(event, Outside):
        if cfg.level == "all" and cfg.topic:
            await _forum_send(bot, cfg.topic, fmt.outside_line(event))
        if critical(event):
            allowed = _outside_allowed(event.repo, time.monotonic())
            if allowed is True:
                await _owner(bot, fmt.outside_alert(event), open_kb(event.url))
            elif allowed is None:
                await _owner(bot, fmt.outside_muted(event.repo), None, loud=False)
    elif isinstance(event, Alert):
        await _owner(bot, fmt.security_alert(event), open_kb(event.url))


def _outside_allowed(repo: str, now: float) -> bool | None:
    """True — send; None — the limit is just reached (say so once); False — keep quiet."""
    seen = _outside.setdefault(repo, deque())
    while seen and now - seen[0] > OUTSIDE_WINDOW:
        seen.popleft()
    seen.append(now)
    if len(seen) <= OUTSIDE_LIMIT:
        return True
    return None if len(seen) == OUTSIDE_LIMIT + 1 else False


T = TypeVar("T")


async def _tg(call: Callable[[], Awaitable[T]]) -> T:
    """A Telegram call that waits out flood control once instead of losing the message."""
    try:
        return await call()
    except TelegramRetryAfter as e:
        if e.retry_after > RETRY_AFTER_MAX:
            raise
        await asyncio.sleep(e.retry_after)
        return await call()


def _push_state(event: Push) -> dict[str, Any]:
    return {"repo": event.repo, "sha": event.sha, "branch": event.branch, "title": event.title,
            "count": event.count, "url": event.url}  # fmt: skip


async def _run(bot: Bot, app: GithubApp, cfg: RepoConfig, run: Run) -> None:
    step = None
    if run.failed:
        try:
            step = await app.failed_step(run.repo, run.run_id)
        except Exception as e:  # the step is a nicety: its failure must not cost the failure message
            logger.info("Failed step of %s #%s unknown: %s", run.repo, run.run_id, e)
    entry = {"status": run.status, "conclusion": run.conclusion, "seconds": run.seconds, "url": run.url, "step": step}
    if run.tag:
        key, base = f"tag:{run.repo}:{run.ref}", {"repo": run.repo, "tag": run.ref}
    else:
        key = f"sha:{run.repo}:{run.sha}"
        base = {"repo": run.repo, "sha": run.sha, "branch": run.ref, "title": run.title}
    await _live_forum(bot, cfg, key, base, run=(run.workflow, entry), show=cfg.level == "all" or run.failed)
    if critical(run):
        await _failure(bot, run, step)
    elif run.passed:
        await _fixed(bot, run)


# ── the forum ──────────────────────────────────────────────────────────────────


async def _live_forum(
    bot: Bot,
    cfg: RepoConfig,
    key: str,
    update: dict[str, Any],
    *,
    run: tuple[str, dict[str, Any]] | None = None,
    show: bool,
) -> None:
    """Merge the update into the message's state; send it, or edit it, when it is to be shown."""
    async with _locks.setdefault(key, asyncio.Lock()):
        item = await store.live(key) or Live(key, 0, 0, {})
        for field, value in update.items():
            if value or field not in item.state:
                item.state[field] = value
        if run is not None:
            item.state.setdefault("runs", {})[run[0]] = run[1]
        shown = item.message_id != 0
        if cfg.topic and (show or shown) and "repo" in item.state:
            text = fmt.release_message(item.state) if key.startswith("tag:") else fmt.commit_message(item.state)
            # Message ids are per chat: after a move to another forum the old id means another message there.
            current = item.message_id if item.chat_id == cfg.topic.chat_id else 0
            if text != item.state.get("_text") or not current:
                message_id = await _forum_put(bot, cfg.topic, current, text)
                if message_id:
                    item.chat_id, item.message_id = cfg.topic.chat_id, message_id
                    item.state["_text"] = text
        await store.keep(item)
    if len(_locks) > 1000:
        for idle in [k for k, lock in _locks.items() if not lock.locked()]:
            del _locks[idle]


async def _forum_put(bot: Bot, topic: Topic, message_id: int, text: str) -> int | None:
    if message_id:
        try:
            await _tg(lambda: bot.edit_message_text(text, chat_id=topic.chat_id, message_id=message_id,
                                                    disable_web_page_preview=True))  # fmt: skip
            return message_id
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                return message_id
            logger.info("Forum message %s not edited (%s), sending anew", message_id, e)
    return await _forum_send(bot, topic, text)


async def _forum_send(bot: Bot, topic: Topic, text: str) -> int | None:
    async def send() -> int:
        sent = await _tg(
            lambda: bot.send_message(
                topic.chat_id, text, message_thread_id=topic.thread_id,
                disable_notification=True, disable_web_page_preview=True,
            )
        )  # fmt: skip
        return sent.message_id

    try:
        message_id = await send()
    except TelegramBadRequest as e:
        reason = str(e).lower()
        if "closed" in reason:
            try:
                await bot.reopen_forum_topic(topic.chat_id, topic.thread_id)
                message_id = await send()
            except TelegramAPIError:
                await _topic_broken(bot, topic)
                return None
        elif "thread" in reason or "topic" in reason:
            await _topic_broken(bot, topic)
            return None
        else:
            raise
    _broken.discard(topic.id)
    return message_id


async def _topic_broken(bot: Bot, topic: Topic) -> None:
    if topic.id in _broken:
        return
    _broken.add(topic.id)
    await _owner(bot, fmt.topic_broken(topic, await store.repos_in_topic(topic.id)), broken_kb(topic.id))


# ── the owner's chat ───────────────────────────────────────────────────────────


async def _owner(bot: Bot, text: str, keyboard: InlineKeyboardMarkup | None, *, loud: bool = True) -> Message:
    return await _tg(
        lambda: bot.send_message(
            settings.telegram_admin_id, text, reply_markup=keyboard,
            disable_notification=not loud, disable_web_page_preview=True,
        )
    )  # fmt: skip


def _owner_key(run: Run) -> str:
    return f"dm:{run.repo}:{run.ref}:{run.workflow}"


async def _failure(bot: Bot, run: Run, step: str | None) -> None:
    key = _owner_key(run)
    async with _locks.setdefault(key, asyncio.Lock()):
        previous = await store.live(key)
        sent = await _owner(bot, fmt.run_failed(run, step), failed_kb(run.url))
        await store.keep(Live(key, sent.chat.id, sent.message_id, {"repo": run.repo, "run_id": run.run_id}))
        if previous:
            await _delete(bot, previous.chat_id, previous.message_id)


async def _fixed(bot: Bot, run: Run) -> None:
    key = _owner_key(run)
    async with _locks.setdefault(key, asyncio.Lock()):
        previous = await store.live(key)
        if previous is None:
            return
        await store.forget(key)
        try:
            await bot.edit_message_text(fmt.run_fixed(run), chat_id=previous.chat_id, message_id=previous.message_id)
        except TelegramAPIError as e:
            logger.info("Fixed failure %s not edited: %s", key, e)
            return
        # Removed by the sweep an hour later; a record, so a restart in between does not keep it forever.
        state = {"fixed_at": time.time()}
        await store.keep(Live(f"fixed:{key}:{previous.message_id}", previous.chat_id, previous.message_id, state))


async def github_sweep(bot: Bot) -> None:
    """Every SWEEP_MINUTES: "снова зелёный" messages older than an hour go; old records are pruned."""
    for item in await store.fixed_before(time.time() - FIXED_KEEP):
        await _delete(bot, item.chat_id, item.message_id)
        await store.forget(item.key)
    await store.prune()


async def _delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError as e:
        logger.info("GitHub message %s not deleted: %s", message_id, e)


# ── buttons ────────────────────────────────────────────────────────────────────

_app: GithubApp | None = None


def use_app(app: GithubApp) -> None:
    global _app
    _app = app


@router.callback_query(GhRerun.filter())
async def rerun_callback(query: CallbackQuery) -> None:
    if not isinstance(query.message, Message) or _app is None:
        await query.answer()
        return
    item = await store.live_by_message(query.message.chat.id, query.message.message_id)
    if item is None or not item.state.get("repo") or not item.state.get("run_id"):
        await query.answer("Этот запуск уже не найти", show_alert=True)
        return
    try:
        await _app.rerun_failed(str(item.state["repo"]), int(item.state["run_id"]))
    except GithubApiError as e:
        logger.warning("Rerun refused: %s", e)
        await query.answer("GitHub не дал перезапустить", show_alert=True)
        return
    await query.answer("Перезапустил упавшие jobs")


@router.callback_query(GhRecreate.filter())
async def recreate_callback(query: CallbackQuery, callback_data: GhRecreate, bot: Bot) -> None:
    topic = await store.topic(callback_data.topic_id)
    if topic is None:
        await query.answer("Темы уже нет в настройках", show_alert=True)
        return
    try:
        created = await bot.create_forum_topic(topic.chat_id, topic.name)
    except TelegramAPIError as e:
        logger.warning("Topic %s not created: %s", topic.name, e)
        await query.answer("Telegram не дал создать тему: у бота есть право «Управление темами»?", show_alert=True)
        return
    new = await store.replace_topic(topic.id, topic.chat_id, created.message_thread_id, topic.name)
    _broken.discard(topic.id)
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(fmt.topic_recreated(new))
        except TelegramAPIError:
            pass
    await query.answer()
