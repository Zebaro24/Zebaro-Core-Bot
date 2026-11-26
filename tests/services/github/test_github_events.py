import sys
from unittest.mock import AsyncMock, MagicMock

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

import pytest

from src.interfaces.tg.formatters import github as fmt
from src.services.github.events import Alert, NewRepos, Outside, Push, Release, Run, critical, parse, safe_url

REPO = {"full_name": "Zebaro24/Zebaro-Core-MCP", "default_branch": "main", "owner": {"login": "Zebaro24"},
        "html_url": "https://github.com/Zebaro24/Zebaro-Core-MCP"}  # fmt: skip
OWNER = {"login": "Zebaro24", "type": "User"}


def push(**over):
    body = {"ref": "refs/heads/main", "after": "abc123", "repository": REPO, "sender": OWNER,
            "commits": [{"id": "1", "message": "a"}, {"id": "abc123", "message": "feat: b\n\nbody"}],
            "head_commit": {"id": "abc123", "message": "feat: b\n\nbody",
                            "url": "https://github.com/Zebaro24/Zebaro-Core-MCP/commit/abc123"}}  # fmt: skip
    body.update(over)
    return body


def workflow_run(action="completed", **run):
    body = {"id": 7, "name": "CI", "head_sha": "abc123", "head_branch": "main", "status": "completed",
            "conclusion": "success", "html_url": "https://github.com/Zebaro24/Zebaro-Core-MCP/actions/runs/7",
            "run_started_at": "2026-11-26T10:00:00Z", "updated_at": "2026-11-26T10:01:23Z",
            "head_commit": {"message": "feat: b"}}  # fmt: skip
    body.update(run)
    return {"action": action, "workflow_run": body, "repository": REPO, "sender": OWNER}


def test_a_push_keeps_its_head_commit_and_count():
    event = parse("push", push())
    assert event == Push("Zebaro24/Zebaro-Core-MCP", "main", "abc123", "feat: b", 2,
                         "https://github.com/Zebaro24/Zebaro-Core-MCP/commit/abc123")  # fmt: skip


@pytest.mark.parametrize("over", [{"ref": "refs/tags/v1.0.0"}, {"deleted": True}, {"commits": []}])
def test_tag_pushes_deleted_branches_and_empty_pushes_are_dropped(over):
    assert parse("push", push(**over)) is None


def test_a_run_on_main_measures_itself():
    event = parse("workflow_run", workflow_run())
    assert isinstance(event, Run)
    assert event.passed and not event.tag and event.default_branch and event.seconds == 83


def test_a_run_on_a_release_tag_is_a_release():
    event = parse("workflow_run", workflow_run(name="CD", head_branch="v0.13.1", conclusion="failure"))
    assert isinstance(event, Run) and event.tag and event.failed and critical(event)


def test_a_failure_on_a_side_branch_is_not_critical():
    event = parse("workflow_run", workflow_run(head_branch="feature", conclusion="failure"))
    assert isinstance(event, Run) and event.failed and not critical(event)


def test_a_cancelled_run_is_not_a_failure():
    event = parse("workflow_run", workflow_run(conclusion="cancelled"))
    assert isinstance(event, Run) and not event.failed and not critical(event)


def test_the_owners_own_issue_is_not_news():
    payload = {"action": "opened", "issue": {"title": "x", "html_url": "https://github.com/i/1"}, "repository": REPO,
               "sender": OWNER}  # fmt: skip
    assert parse("issues", payload) is None


def test_someone_elses_issue_is_critical_a_bots_pr_is_not():
    issue = parse("issues", {"action": "opened", "issue": {"title": "Bug", "html_url": "https://github.com/i/1"},
                             "repository": REPO, "sender": {"login": "alice", "type": "User"}})  # fmt: skip
    pr = parse("pull_request", {"action": "opened", "pull_request": {"title": "Bump"}, "repository": REPO,
                                "sender": {"login": "dependabot[bot]", "type": "Bot"}})  # fmt: skip
    assert isinstance(issue, Outside) and critical(issue)
    assert isinstance(pr, Outside) and pr.bot and not critical(pr)


def test_a_dependabot_alert_is_critical():
    payload = {"action": "created", "repository": REPO, "sender": OWNER,
               "alert": {"html_url": "https://github.com/a/1", "dependency": {"package": {"name": "httpx"}},
                         "security_advisory": {"severity": "high", "summary": "SSRF"}}}  # fmt: skip
    event = parse("dependabot_alert", payload)
    assert event == Alert("Zebaro24/Zebaro-Core-MCP", "high", "httpx", "SSRF", "https://github.com/a/1")
    assert critical(event)


def test_new_repos_of_the_installation():
    payload = {"action": "added", "repositories_added": [{"full_name": "Zebaro24/New"}], "sender": OWNER}
    assert parse("installation_repositories", payload) == NewRepos(("Zebaro24/New",))


def test_a_published_release_keeps_its_whole_notes():
    release = {"tag_name": "v1.0.0", "html_url": "https://github.com/r/1", "body": "\n### Changed\n- x"}
    payload = {"action": "published", "repository": REPO, "sender": OWNER, "release": release}
    assert parse("release", payload) == Release(
        "Zebaro24/Zebaro-Core-MCP", "v1.0.0", "https://github.com/r/1", release["body"]
    )


def test_only_github_links_reach_a_message():
    assert safe_url("https://github.com/x") == "https://github.com/x"
    assert safe_url("javascript:alert(1)") == "" and safe_url("https://evil.example/x") == ""


def test_text_from_github_is_escaped():
    text = fmt.commit_message({"repo": "o/r", "branch": "main", "title": "<b>x</b> & y", "url": "", "sha": "a"})
    assert "&lt;b&gt;x&lt;/b&gt; &amp; y" in text


def test_durations_read_like_the_chat():
    assert (fmt.duration(83), fmt.duration(9), fmt.duration(None)) == ("1м 23с", "9с", "")


def test_changelog_markdown_reads_well_in_telegram():
    text = """### Changed

- **GitHub rebuilt.** The bot is now a GitHub App on all your repos: new repos show up at
  once, see [docs](https://github.com/o/r/blob/main/README.md) and `/github`.
  - nested <tag> & more
- Second item

A paragraph wrapped
in the file."""
    assert fmt.markdown(text).splitlines() == [
        "<b>Changed</b>",
        "",
        "• <b>GitHub rebuilt.</b> The bot is now a GitHub App on all your repos: new repos show up at once, see "
        '<a href="https://github.com/o/r/blob/main/README.md">docs</a> and <code>/github</code>.',
        "   ◦ nested &lt;tag&gt; &amp; more",
        "• Second item",
        "",
        "A paragraph wrapped in the file.",
    ]


def test_code_keeps_its_stars_and_a_link_needs_https():
    assert fmt.markdown("`**x**` [a](javascript:alert(1))") == "<code>**x**</code> [a](javascript:alert(1))"


def test_long_notes_are_cut_at_a_line():
    notes = "\n".join(f"- item {n} " + "x" * 50 for n in range(200))
    text = fmt.release_message({"repo": "o/r", "tag": "v1.0.0", "notes": notes, "release_url": "https://github.com/r"})
    assert len(text) < 4096 and text.count("<blockquote") == 1 and "…" in text
