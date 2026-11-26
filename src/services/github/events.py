"""GitHub webhook payloads → small typed events, and which of them need the owner. Pure: no I/O here.

Only what the bot shows is kept. A push to a tag, a deleted branch, PR updates, CI's intermediate states
beyond "running" — none of it becomes an event of its own.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
_FAILED = {"failure", "timed_out", "startup_failure"}
_GITHUB = "https://github.com/"
# A release body is kept up to this long; the message shows what fits (formatters/github.py).
NOTES_KEPT = 6000


@dataclass(frozen=True)
class Push:
    repo: str
    branch: str
    sha: str
    title: str
    count: int
    url: str


@dataclass(frozen=True)
class Run:
    repo: str
    workflow: str
    run_id: int
    sha: str
    ref: str  # a branch, or the tag of a release
    tag: bool
    default_branch: bool
    status: str  # queued | in_progress | completed
    conclusion: str | None
    title: str
    url: str
    seconds: int | None

    @property
    def failed(self) -> bool:
        return self.status == "completed" and self.conclusion in _FAILED

    @property
    def passed(self) -> bool:
        return self.status == "completed" and self.conclusion == "success"

    @property
    def watched(self) -> bool:
        """Failures here matter: the main branch, or a release."""
        return self.tag or self.default_branch


@dataclass(frozen=True)
class Release:
    repo: str
    tag: str
    url: str
    notes: str  # the release body: the tag's CHANGELOG section, Markdown


@dataclass(frozen=True)
class Outside:
    """Someone else's activity: an issue, a PR, a star, a fork."""

    repo: str
    kind: str  # issue | pr | star | fork
    who: str
    title: str
    url: str
    bot: bool


@dataclass(frozen=True)
class Alert:
    repo: str
    severity: str
    package: str
    summary: str
    url: str


@dataclass(frozen=True)
class NewRepos:
    names: tuple[str, ...]


Event = Push | Run | Release | Outside | Alert | NewRepos


def safe_url(url: Any) -> str:
    """Only github.com links reach a message; anything else is dropped."""
    return url if isinstance(url, str) and url.startswith(_GITHUB) else ""


def first_line(text: Any, limit: int = 120) -> str:
    for line in str(text or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def _seconds(start: Any, end: Any) -> int | None:
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((b - a).total_seconds()))


def parse(event: str, payload: dict[str, Any], me: str = "") -> Event | None:
    """`me` — the owner's login: their own issues, PRs and stars are not someone else's."""
    repo_info = payload.get("repository") or {}
    repo = str(repo_info.get("full_name") or "")
    owner = (me or str((repo_info.get("owner") or {}).get("login") or "")).lower()
    sender = payload.get("sender") or {}
    who = str(sender.get("login") or "")
    mine = who.lower() == owner
    action = payload.get("action")

    if event == "push":
        ref = str(payload.get("ref") or "")
        commits = payload.get("commits") or []
        if not ref.startswith("refs/heads/") or payload.get("deleted") or not commits:
            return None
        head = payload.get("head_commit") or commits[-1]
        return Push(
            repo=repo,
            branch=ref.removeprefix("refs/heads/"),
            sha=str(payload.get("after") or head.get("id") or ""),
            title=first_line(head.get("message")),
            count=len(commits),
            url=safe_url(head.get("url")),
        )

    if event == "workflow_run":
        run = payload.get("workflow_run") or {}
        if action not in ("requested", "in_progress", "completed"):
            return None
        ref = str(run.get("head_branch") or "")
        status = str(run.get("status") or "")
        return Run(
            repo=repo,
            workflow=str(run.get("name") or "workflow"),
            run_id=int(run.get("id") or 0),
            sha=str(run.get("head_sha") or ""),
            ref=ref,
            tag=bool(_RELEASE_TAG.match(ref)),
            default_branch=ref == repo_info.get("default_branch"),
            status=status,
            conclusion=run.get("conclusion"),
            title=first_line((run.get("head_commit") or {}).get("message") or run.get("display_title")),
            url=safe_url(run.get("html_url")),
            seconds=_seconds(run.get("run_started_at"), run.get("updated_at")) if status == "completed" else None,
        )

    if event == "release":
        release = payload.get("release") or {}
        if action != "published":
            return None
        return Release(
            repo=repo,
            tag=str(release.get("tag_name") or ""),
            url=safe_url(release.get("html_url")),
            notes=str(release.get("body") or "")[:NOTES_KEPT],
        )

    if event in ("issues", "pull_request"):
        item = payload.get("issue") or payload.get("pull_request") or {}
        if action != "opened" or not who or mine:
            return None
        return Outside(
            repo=repo,
            kind="issue" if event == "issues" else "pr",
            who=who,
            title=first_line(item.get("title")),
            url=safe_url(item.get("html_url")),
            bot=sender.get("type") == "Bot",
        )

    if event in ("watch", "fork"):
        if event == "watch" and action != "started":
            return None
        if mine:
            return None
        return Outside(repo=repo, kind="star" if event == "watch" else "fork", who=who, title="",
                       url=safe_url(repo_info.get("html_url")), bot=sender.get("type") == "Bot")  # fmt: skip

    if event == "dependabot_alert":
        alert = payload.get("alert") or {}
        if action not in ("created", "reopened"):
            return None
        advisory = alert.get("security_advisory") or {}
        package = ((alert.get("dependency") or {}).get("package") or {}).get("name") or ""
        return Alert(
            repo=repo,
            severity=str(advisory.get("severity") or "unknown"),
            package=str(package),
            summary=first_line(advisory.get("summary")),
            url=safe_url(alert.get("html_url")),
        )

    if event == "installation_repositories" and action == "added":
        names = tuple(str(r.get("full_name")) for r in payload.get("repositories_added") or [] if r.get("full_name"))
        return NewRepos(names) if names else None

    return None


def critical(event: Event) -> bool:
    """What goes to the owner's chat, loud, with buttons. Everything else is the forum's, silent."""
    if isinstance(event, Run):
        return event.failed and event.watched
    if isinstance(event, Outside):
        return event.kind in ("issue", "pr") and not event.bot
    return isinstance(event, Alert)
