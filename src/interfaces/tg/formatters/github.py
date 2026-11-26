"""GitHub in Telegram: the forum's quiet lines and the owner's loud ones. Everything from GitHub is escaped.

A live message is rendered from its stored state, so an edit always shows the whole picture: a commit with
every workflow that ran on it, a release with its CD run and the first line of its notes.
"""

import html
from typing import Any

from src.services.github.events import Alert, NewRepos, Outside, Run
from src.services.github.store import Level, RepoConfig, Topic

LEVEL_LABEL: dict[str, str] = {"all": "🔔 всё", "fails": "⚠️ только сбои", "off": "⛔ выкл"}
_RUN_ICON = {"success": "✅", "failure": "❌", "timed_out": "❌", "startup_failure": "❌", "cancelled": "⏹"}


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
    parts = []
    for name, run in runs.items():
        part = f"{_link(run.get('url', ''), name)} {run_icon(run)}"
        if run.get("seconds") is not None:
            part += f" {duration(run['seconds'])}"
        if run.get("step"):
            part += f" — {_e(run['step'])}"
        parts.append(part)
    return " · ".join(parts)


def commit_message(state: dict[str, Any]) -> str:
    """`✅ MCP · main · refactor(arch): … (+2)` and the workflows under it."""
    runs: dict[str, dict[str, Any]] = state.get("runs") or {}
    head = f"{overall(runs) if runs else '📌'} <b>{_e(short(state['repo']))}</b> · {_e(state.get('branch', ''))}"
    title = _link(state.get("url", ""), state.get("title") or state.get("sha", "")[:7])
    count = int(state.get("count") or 1)
    text = f"{head} · {title}" + (f" (+{count - 1})" if count > 1 else "")
    return text + (f"\n{_runs_line(runs)}" if runs else "")


def release_message(state: dict[str, Any]) -> str:
    """`🚀 MCP v0.13.1 · на проде ✅ 2м 10с` and the first line of the release notes."""
    runs: dict[str, dict[str, Any]] = state.get("runs") or {}
    icon = overall(runs) if runs else ("✅" if state.get("release_url") else "⏳")
    word = {"✅": "на проде", "❌": "релиз не прошёл", "⏳": "релиз идёт"}.get(icon, "релиз")
    name = _link(state.get("release_url", ""), f"{short(state['repo'])} {state['tag']}")
    seconds = [r["seconds"] for r in runs.values() if r.get("seconds") is not None]
    text = f"🚀 <b>{name}</b> · {word} {icon}" + (f" {duration(max(seconds))}" if seconds and icon == "✅" else "")
    if icon != "✅" and runs:
        text += f"\n{_runs_line(runs)}"
    if state.get("note"):
        text += f"\n{_e(state['note'])}"
    return text


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
        text = f"🔴 <b>{_e(short(run.repo))}</b> · {_e(run.ref)} · {_e(run.workflow)} упал"
        tail = _e(run.title)
    if step:
        text += f"\nШаг: «{_e(step)}»"
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


def admin_list(repos: list[tuple[RepoConfig, bool]], has_forum: bool) -> str:
    """The /github screen's text; the repos themselves are its buttons."""
    lines = ["🐙 <b>GitHub</b>", "Уровень · тема в форуме. Сбои приходят сюда у всех репо, кроме «выкл»."]
    if not repos:
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
