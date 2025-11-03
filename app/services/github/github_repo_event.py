import asyncio
import logging
from datetime import datetime
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger("github.events")


class GithubRepoEvent:
    def __init__(self, full_repo_name: str, bot: Bot, tg_chat_id: int, thread_id: int | None = None):
        self.full_repo_name = full_repo_name
        self.bot = bot
        self.tg_chat_id = tg_chat_id
        self.thread_id = thread_id
        self._messages_cache: dict[Any, int] = {}

    async def send_message(self, message, notification=False):
        return await self.bot.send_message(
            self.tg_chat_id,
            message,
            message_thread_id=self.thread_id,
            disable_web_page_preview=True,
            disable_notification=not notification,
        )

    async def send_or_edit_message(self, key, text: str):
        message_id = self._messages_cache.get(key)

        if message_id:
            try:
                await self.bot.edit_message_text(chat_id=self.tg_chat_id, message_id=message_id, text=text)
                return
            except TelegramBadRequest as e:
                logger.warning(f"Cannot edit message for key {key}: {e}")

        sent = await self.send_message(text)
        self._messages_cache[key] = sent.message_id

    async def handle(self, event_name, payload):
        if hasattr(self, event_name):
            method = getattr(self, event_name)
            if asyncio.iscoroutinefunction(method):
                await method(payload)
            else:
                method(payload)
        else:
            logger.warning(f"No handler for the event: {event_name}")

    # <--- Events --->
    async def push(self, payload):
        repo = payload.get("repository", {}).get("full_name", "unknown repo")
        pusher = payload.get("pusher", {}).get("name", "unknown user")
        commits = payload.get("commits", [])
        branch = payload.get("ref", "").replace("refs/heads/", "")

        header = f"🐙 <b>GitHub Push в {repo}</b>\n"
        info = f"👤 <b>{pusher}</b> → <code>{branch}</code>\n"

        if not commits:
            await self.send_message(header + info + "⚠️ Нет новых коммитов.")
            return

        commit_lines = []
        for c in commits:
            short_id = c["id"][:7]
            msg = c["message"].strip().replace("\n", " ")
            author = c.get("author", {}).get("name", "unknown")
            url = c.get("url", "")
            commit_lines.append(f"• <a href='{url}'><code>{short_id}</code></a> — {msg} ({author})")

        await self.send_message(header + info + "\n".join(commit_lines))

    async def pull_request(self, payload):
        action = payload.get("action", "unknown")
        pr = payload.get("pull_request", {})
        repo = pr.get("base", {}).get("repo", {}).get("full_name", "unknown repo")
        title = pr.get("title", "no title")
        user = pr.get("user", {}).get("login", "unknown user")
        url = pr.get("html_url", "")
        base = pr.get("base", {}).get("ref", "unknown")
        head = pr.get("head", {}).get("ref", "unknown")
        merged = pr.get("merged", False)
        created_at = pr.get("created_at", "")
        updated_at = pr.get("updated_at", "")

        msg = (
            f"🔀 <b>GitHub Pull Request {action.upper()}</b>\n"
            f"📦 Repo: <b>{repo}</b>\n"
            f"🧠 Branch: <code>{head}</code> → <code>{base}</code>\n"
            f"👤 Author: <b>{user}</b>\n"
            f"📝 Title: {title}\n"
        )

        if merged:
            msg += "✅ <b>Merged!</b>\n"

        msg += f"🕒 Created: {created_at}\n🔄 Updated: {updated_at}\n🔗 <a href='{url}'>Открыть PR</a>"
        await self.send_message(msg)

    async def workflow_run(self, payload):
        workflow_run = payload.get("workflow_run", {})
        workflow_id = workflow_run.get("id")
        repo = workflow_run.get("repository", {}).get("full_name", self.full_repo_name)
        name = workflow_run.get("name", "unknown workflow")
        status = workflow_run.get("status", "unknown")
        conclusion = workflow_run.get("conclusion", None)
        actor = workflow_run.get("actor", {}).get("login", "unknown user")
        url = workflow_run.get("html_url", "")
        event_type = workflow_run.get("event", "unknown")
        created_at = workflow_run.get("created_at", None)

        time_str = ""
        if created_at:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")

        emoji = {
            "success": "✅",
            "failure": "❌",
            "cancelled": "🚫",
            "in_progress": "🕒",
        }.get(conclusion, "⚙️")

        status_line = f"⏱ Status: <u>{status.replace('_', ' ').title()}</u>"
        result_line = f"🎯 Result: {conclusion.upper() if conclusion else '…'}"

        text = (
            f"{emoji} <b>GitHub Workflow:</b> <i>{name}</i>\n"
            f"📦 Repo: <b>{repo}</b>\n"
            f"👤 Triggered by: <b>{actor}</b>\n"
            f"🚀 Event: <b>{event_type}</b>\n"
            f"🕒 Time: {time_str}\n"
            f"{status_line}\n"
            f"{result_line}\n"
            f"🔗 <a href='{url}'>Open workflow</a>"
        )

        if conclusion is None or conclusion == "in_progress":
            await self.send_or_edit_message(workflow_id, text)
        else:
            await self.send_or_edit_message(workflow_id, text)
            notify_text = (
                f"🎉 <b>Workflow Finished:</b> <i>{name}</i> ({conclusion.upper()})\n"
                f"📦 Repo: {repo}\n"
                f"🚀 Event: {event_type}\n"
                f"🕒 Time: {time_str}\n"
                f"🔗 <a href='{url}'>Open workflow</a>"
            )
            message = await self.send_message(notify_text)
            await asyncio.sleep(10)
            await message.delete()
