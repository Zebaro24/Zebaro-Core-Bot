#!/usr/bin/env python3
"""PreToolUse(Bash|PowerShell) guard for Zebaro-Core-Bot — the two gates that matter.

Commits are free: they are a local savepoint and nothing more. What is NOT free
is anything that leaves this machine, because that is what GitHub and the
production server see. So exactly two things are gated, and both open only via a
skill that ran the quality gate first:

  git push            -> needs .claude/.approve-push     (minted by /push)
  git push v<tag>     -> needs .claude/.approve-release  (minted by /release)

On top of that, two absolutes:

  * dangerous git is always refused (force-push, --no-verify, reset --hard
    origin, --no-gpg-sign) -- if you truly mean it, the owner types it;
  * a commit, a tag or a PR must never mention the assistant or its vendor and
    must never carry Co-Authored-By. The author of this repository is the human, always.

Markers are one-shot: consumed on use, and ignored if older than TTL_SECONDS so
an approval granted an hour ago cannot be spent on today's unreviewed change.

Denies with exit 2 + a deny decision; allows with exit 0. Stdlib only.
"""
import json
import os
import re
import sys
import time

TTL_SECONDS = 15 * 60

# Traces of the tool that must never reach the repository history.
# No bare "AI" here, unlike Bento: AI/ML roles are this bot's subject matter, and
# "fix(jobs): score AI roles higher" is an honest commit.
ATTRIBUTION = re.compile(r"(?i)co-authored-by|generated with|🤖|claude|anthropic")

# Values of -m / --message / --body / --title. Parsed on their own rather than the whole
# command: `git add CLAUDE.md && git commit -m "..."` must not be blocked by a file name —
# the rule is about what goes into the message, not what is mentioned next to it.
MESSAGE_ARG = re.compile(
    r"""(?:\s-a?m|\s--message|\s-b|\s--body|\s-t|\s--title)(?:=|\s+)(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))""",
    re.S,
)
# Heredoc bodies: `git commit -F - <<'EOF' ... EOF` and `-m "$(cat <<'EOF' ... EOF)"`.
HEREDOC = re.compile(r"""<<-?\s*['"]?(\w+)['"]?[^\n]*\n(.*?)\n\s*\1\b""", re.S)
# -F <file> / --file=<file>: the message lives in a file, so read the file.
MESSAGE_FILE = re.compile(r"""(?:\s-F|\s--file)(?:=|\s+)(?:"([^"]+)"|'([^']+)'|(\S+))""")

WRITES_MESSAGE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:commit|tag)\b|\bgh\s+pr\s+(?:create|edit)\b")


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(2)


def consume(root, name, ttl=TTL_SECONDS):
    """True if a fresh approval marker exists; consumes it. False otherwise."""
    path = os.path.join(root, ".claude", name)
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    return age <= ttl


def message_texts(cmd, cwd):
    texts = [next(g for g in m.groups() if g is not None) for m in MESSAGE_ARG.finditer(cmd)]
    texts += [m.group(2) for m in HEREDOC.finditer(cmd)]
    for m in MESSAGE_FILE.finditer(cmd):
        path = next(g for g in m.groups() if g is not None)
        if path == "-":
            continue
        try:
            with open(os.path.join(cwd, path), encoding="utf-8", errors="replace") as f:
                texts.append(f.read())
        except OSError:
            pass
    return texts


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except Exception:
        return 0

    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return 0

    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or "."
    cwd = data.get("cwd") or root

    # 1) dangerous git — never, not even with an approval
    if (re.search(r"push\s+[^|;&]*(--force\b|--force-with-lease\b|\s-f\b|\s\+\S)", cmd)
            or re.search(r"--no-verify\b", cmd)
            or re.search(r"--no-gpg-sign\b", cmd)
            or re.search(r"reset\s+--hard\s+origin", cmd)):
        deny(
            "Опасная git-команда заблокирована (force-push / --no-verify / "
            "--no-gpg-sign / reset --hard origin). Если это правда нужно — "
            "владелец делает это руками."
        )

    # 2) the author is the human — in commits, tags and pull requests
    if WRITES_MESSAGE.search(cmd) and any(ATTRIBUTION.search(t) for t in message_texts(cmd, cwd)):
        deny(
            "В сообщении коммита, тега или PR не должно быть Co-Authored-By и упоминаний "
            "ассистента / AI / Anthropic. Автор репозитория — человек. "
            "Формат коммита: одна строка `type(scope): summary`."
        )

    # 3) push and deploy — the two ways out of this machine
    if re.search(r"\bgit\s+(?:-C\s+\S+\s+)?push\b", cmd):
        pushes_tag = bool(
            re.search(r"--tags\b", cmd)
            or re.search(r"--follow-tags\b", cmd)
            or re.search(r"refs/tags/", cmd)
            or re.search(r"\bv\d+\.\d+\.\d+", cmd)
        )
        if pushes_tag:
            if consume(root, ".approve-release"):
                return 0
            deny(
                "Пуш тега vX.Y.Z = деплой на прод. Он идёт только через /release: "
                "строгий гейт → версия → CHANGELOG → подтверждение владельца. "
                "Скажи «release», не пушь тег руками."
            )
        if consume(root, ".approve-push"):
            return 0
        deny(
            "git push уходит наружу и требует одобрения. Запусти /push — он прогонит "
            "гейт и выпишет одноразовый маркер. Скажи «push»."
        )

    return 0


sys.exit(main())
