"""GitHub in Telegram: the forum's quiet lines and the owner's loud ones. Everything from GitHub is escaped.

A live message is rendered from its stored state, so an edit always shows the whole picture: a commit with
every workflow that ran on it, a release with its CD run and its whole changelog section (Markdown turned
into Telegram's HTML, in a collapsible quote).
"""

import html
import re
from typing import Any

from src.services.github.events import Alert, NewRepos, Outside, Run
from src.services.github.store import Level, RepoConfig, Topic

LEVEL_LABEL: dict[str, str] = {"all": "🔔 всё", "fails": "⚠️ только сбои", "off": "⛔ выкл"}
_RUN_ICON = {"success": "✅", "failure": "❌", "timed_out": "❌", "startup_failure": "❌", "cancelled": "⏹"}
# A Telegram message holds 4096 characters; the notes get what is left after the head and the links.
NOTES_MAX = 3000


def short(repo: str) -> str:
    return repo.rsplit("/", 1)[-1]


def _e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _link(url: str, text: str) -> str:
    return f'<a href="{_e(url)}">{_e(text)}</a>' if url else _e(text)


def duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    minutes, sec = divmod(seconds, 60)
    return f"{minutes}м {sec:02d}с" if minutes else f"{sec}с"


def run_icon(run: dict[str, Any]) -> str:
    if run.get("status") != "completed":
        return "⏳"
    return _RUN_ICON.get(run.get("conclusion") or "", "➖")


def overall(runs: dict[str, dict[str, Any]]) -> str:
    icons = [run_icon(r) for r in runs.values()]
    if "❌" in icons:
        return "❌"
    if "⏳" in icons:
        return "⏳"
    return "✅" if icons and all(i == "✅" for i in icons) else "➖"


def _runs_line(runs: dict[str, dict[str, Any]]) -> str:
    """`✅ CI 1м 23с · ⏳ CD` — each workflow linked to its run; a failure says where."""
    parts = []
    for name, run in runs.items():
        part = f"{run_icon(run)} {_link(run.get('url', ''), name)}"
        if run.get("seconds") is not None:
            part += f" {duration(run['seconds'])}"
        if run.get("step"):
            part += f" — <i>{_e(run['step'])}</i>"
        parts.append(part)
    return " · ".join(parts)


# ── Markdown (a CHANGELOG section) → Telegram HTML ─────────────────────────────

_BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str) -> str:
    """Escape, then `code`, **bold** and [links](https://…) — code first, so nothing inside it is touched."""
    out = []
    for i, part in enumerate(text.split("`")):
        if i % 2:
            out.append(f"<code>{_e(part)}</code>")
            continue
        part = _e(part)
        part = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', part)
        out.append(_BOLD.sub(r"<b>\1</b>", part))
    return "".join(out)


def markdown(text: str) -> str:
    """Paragraphs, headings and (nested) bullets; a line wrapped in the file joins the line it continues."""
    blocks: list[tuple[str, int, str]] = []  # kind, depth, text
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            blocks.append(("gap", 0, ""))
            continue
        heading = _HEADING.match(line.strip())
        bullet = _BULLET.match(line)
        if heading:
            blocks.append(("head", 0, heading.group(1)))
        elif bullet:
            blocks.append(("item", len(bullet.group(1)) // 2, bullet.group(2)))
        elif blocks and blocks[-1][0] in ("item", "para"):
            kind, depth, so_far = blocks[-1]
            blocks[-1] = (kind, depth, f"{so_far} {line.strip()}")
        else:
            blocks.append(("para", 0, line.strip()))
    lines: list[str] = []
    for kind, depth, body in blocks:
        if kind == "gap":
            if lines and lines[-1] != "":
                lines.append("")
        elif kind == "head":
            lines.append(f"<b>{_inline(body)}</b>")
        elif kind == "item":
            lines.append(f"{'   ' * depth}{'•' if depth == 0 else '◦'} {_inline(body)}")
        else:
            lines.append(_inline(body))
    return "\n".join(lines).strip()


def _cut(text: str, limit: int) -> str:
    """At most `limit` characters of Markdown, cut at a line, so no tag is ever split."""
    if len(text) <= limit:
        return text
    kept = text[:limit].rsplit("\n", 1)[0]
    return f"{kept}\n…"


# ── forum messages ─────────────────────────────────────────────────────────────


def commit_message(state: dict[str, Any]) -> str:
    """Head (status, repo, branch), the commit, and the workflows that ran on it."""
    runs: dict[str, dict[str, Any]] = state.get("runs") or {}
    branch = f"<code>{_e(state.get('branch', ''))}</code>"
    head = f"{overall(runs) if runs else '📌'} <b>{_e(short(state['repo']))}</b> · {branch}"
    title = _link(state.get("url", ""), state.get("title") or state.get("sha", "")[:7])
    count = int(state.get("count") or 1)
    lines = [head, title + (f" <i>+{count - 1}</i>" if count > 1 else "")]
    if runs:
        lines.append(_runs_line(runs))
    return "\n".join(lines)


def release_message(state: dict[str, Any]) -> str:
    """`🚀 MCP v0.13.1 · на проде ✅ 2м 10с`, the changelog section as a collapsible quote, links."""
    runs: dict[str, dict[str, Any]] = state.get("runs") or {}
    icon = overall(runs) if runs else ("✅" if state.get("release_url") else "⏳")
    word = {"✅": "на проде", "❌": "релиз не прошёл", "⏳": "релиз идёт"}.get(icon, "релиз")
    seconds = [r["seconds"] for r in runs.values() if r.get("seconds") is not None]
    took = f" · {duration(max(seconds))}" if seconds and icon == "✅" else ""
    lines = [f"🚀 <b>{_e(short(state['repo']))} {_e(state['tag'])}</b> · {word} {icon}{took}"]
    if icon != "✅" and runs:
        lines.append(_runs_line(runs))
    notes = markdown(_cut(str(state.get("notes") or ""), NOTES_MAX))
    if notes:
        lines.append(f"<blockquote expandable>{notes}</blockquote>")
    links = [_link(state.get("release_url", ""), "Release")] if state.get("release_url") else []
    links += [_link(r["url"], name) for name, r in runs.items() if r.get("url")]
    if links:
        lines.append(" · ".join(links))
    return "\n".join(lines)


def outside_line(event: Outside) -> str:
    what = {"issue": "📨 issue", "pr": "🔀 PR", "star": "⭐ звезда", "fork": "🍴 форк"}[event.kind]
    text = f"{what} · <b>{_e(short(event.repo))}</b> · от {_e(event.who)}"
    return text + (f"\n{_link(event.url, event.title)}" if event.title else "")


# ── the owner's chat ───────────────────────────────────────────────────────────


def run_failed(run: Run, step: str | None) -> str:
    if run.tag:
        text = f"⚠️ <b>{_e(short(run.repo))} {_e(run.ref)}</b> — релиз не прошёл ({_e(run.workflow)})"
        tail = "Прод остался на прошлой версии: CD откатывает сам."
    else:
        text = f"🔴 <b>{_e(short(run.repo))}</b> · <code>{_e(run.ref)}</code> · {_e(run.workflow)} упал"
        tail = _e(run.title)
    if step:
        text += f"\nШаг: <i>{_e(step)}</i>"
    return f"{text}\n{tail}" if tail else text


def run_fixed(run: Run) -> str:
    where = f"{short(run.repo)} {run.ref}" if run.tag else f"{short(run.repo)} · {run.ref}"
    return f"✅ <b>{_e(where)}</b> · {_e(run.workflow)} снова зелёный"


def outside_alert(event: Outside) -> str:
    return outside_line(event)


def security_alert(event: Alert) -> str:
    text = f"🛡 <b>{_e(short(event.repo))}</b> · уязвимость {_e(event.severity)} в {_e(event.package)}"
    return text + (f"\n{_e(event.summary)}" if event.summary else "")


def new_repos(event: NewRepos) -> str:
    names = ", ".join(f"<b>{_e(short(n))}</b>" for n in event.names)
    return f"🆕 Новые репо: {names}\nСбои пишу сюда; в форум — когда выберешь тему в /github."


def topic_bound(topic: Topic) -> str:
    return f"📌 Тема «{_e(topic.name)}» привязана. Репо в неё — в /github."


def topic_recreated(topic: Topic) -> str:
    return f"🧩 Тема «{_e(topic.name)}» создана заново, репо пишут в неё."


def outside_muted(repo: str) -> str:
    return f"🔇 <b>{_e(short(repo))}</b>: слишком много чужих issue и PR за час — дальше только в форум."


def topic_broken(topic: Topic, repos: list[str]) -> str:
    names = ", ".join(_e(short(r)) for r in repos) or "—"
    return f"🧩 Тема «{_e(topic.name)}» в форуме недоступна (удалена?)\nНе дошло: {names}"


# ── admin ──────────────────────────────────────────────────────────────────────


def admin_list(total: int, page: int, pages: int, has_forum: bool) -> str:
    """The /github screen's text; the repos themselves are its buttons."""
    lines = ["🐙 <b>GitHub</b>", "Уровень · тема в форуме. Сбои приходят сюда у всех репо, кроме «выкл»."]
    if total:
        lines.append(f"Репо: {total}" + (f" · страница {page + 1} из {pages}" if pages > 1 else ""))
    else:
        lines.append("\nРепо нет: App не установлен или ничего не видит.")
    if not has_forum:
        lines.append(
            "\nФорум не привязан: добавь бота в форум админом (право «Управление темами») и напиши /bind в теме."
        )
    return "\n".join(lines)


def repo_button(cfg: RepoConfig, private: bool) -> str:
    icon = LEVEL_LABEL[cfg.level].split()[0]
    topic = f" · {cfg.topic.name}" if cfg.topic else ""
    return f"{icon} {'🔒 ' if private else ''}{short(cfg.full_name)}{topic}"


def admin_repo(cfg: RepoConfig, private: bool) -> str:
    lines = [
        f"🐙 <b>{_e(cfg.full_name)}</b>{' 🔒' if private else ''}",
        f"Уровень: {LEVEL_LABEL[cfg.level]}",
        f"Тема: {_e(cfg.topic.name) if cfg.topic else '— (в форум ничего)'}",
    ]
    if private:
        lines.append("\n🔒 Приватный репо: в форуме его коммиты увидят все участники.")
    return "\n".join(lines)


def level_name(level: Level) -> str:
    return LEVEL_LABEL[level]
