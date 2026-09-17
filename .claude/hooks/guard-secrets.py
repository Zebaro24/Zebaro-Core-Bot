#!/usr/bin/env python3
"""PreToolUse(Bash|PowerShell) guard for Zebaro-Core-Bot — keep real secrets out of the transcript.

`.claude/settings.json` already denies *reading* secret files with the Read tool.
This closes the other doors: a shell command that prints the same values. Dumping
`.env` from a shell and reading it with the Read tool have identical consequences —
the token lands in the transcript, where it is quotable, loggable and impossible
to take back.

This bot's real secrets: the Telegram and Discord bot tokens, the GitHub token and
webhook secret, the job-stats API token, the SSH key for the prod server. They live
in `.env`, in GitHub Actions secrets and — on the server — in the bot container's
environment. So besides env files this also refuses the Docker commands that print
a container's environment.

What stays allowed: `.env.example` (names, not values), `docker inspect` with a
`--format` that picks a field, `docker compose config -q`.

Every pattern is deliberately narrow: a guard that blocks ordinary work gets routed
around, and then it protects nothing at all.

Denies with exit 2; allows with exit 0. Stdlib only.
"""
import json
import re
import sys

# Commands that dump a file's contents, anchored to a command position inside one simple
# command (see SEGMENTS) so that "concatenate" or "only" are not read as `cat` or `nl`.
READERS = re.compile(
    r"(?:^|['\"`(]|\bsudo\s+|\bxargs\s+)\s*"
    r"(cat|tac|type|more|less|head|tail|bat|nl|strings|od|xxd|sed|awk|grep|"
    r"Get-Content|gc|Select-String|sls)\b",
    re.IGNORECASE,
)
# The reader and the secret path must sit in the same simple command. Checked across the
# whole line, `grep x .gitignore` next to a Python heredoc that merely mentions ".env"
# was refused — and a guard that blocks ordinary work gets routed around.
SEGMENTS = re.compile(r"[|;&\n]+")

# Secret-bearing paths. The lookbehind keeps `self.env`, `os.environ` and
# `settings.environment` from tripping the guard.
SECRET_PATH = re.compile(
    r"(?<![\w.])\.env(?!\.example)(\.[\w-]+)?(?!\.example)(?![\w])"
    r"|_secrets[/\\]"
    r"|\.pem\b"
    r"|id_ed25519(?!\.pub)"
    r"|id_rsa(?!\.pub)"
)

# A bare dump of the whole environment prints every token in the process.
FULL_ENV_DUMP = re.compile(r"(?:^|[|;&]\s*)(env|printenv|set|Get-ChildItem\s+env:|ls\s+env:|dir\s+env:)\s*($|[|;&])")

# Docker commands that print a container's environment — on the server that is
# every bot token at once.
DOCKER_INSPECT = re.compile(r"\bdocker\s+(?:container\s+)?inspect\b(?![^|;&]*(?:\s-f\b|--format))")
DOCKER_EXEC_ENV = re.compile(r"\bdocker\s+exec\b[^|;&]*\b(env|printenv)\b|\bdocker\s+exec\b[^|;&]*/proc/\d+/environ")
COMPOSE_CONFIG = re.compile(r"\bdocker[\s-]compose\b[^|;&]*\bconfig\b(?![^|;&]*(?:\s-q\b|--quiet|--services))")


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(2)


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except Exception:
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return 0

    if any(READERS.search(s.strip()) and SECRET_PATH.search(s) for s in SEGMENTS.split(cmd)):
        deny(
            "Команда печатает секретный файл (.env, _secrets/ или приватный ключ) — его "
            "содержимое попало бы в переписку. Имена переменных смотри в `.env.example` "
            "и `src/config.py`, а значения спроси у владельца."
        )

    if FULL_ENV_DUMP.search(cmd):
        deny("Полный дамп переменных окружения покажет токены. Запроси конкретную переменную по имени.")

    if DOCKER_INSPECT.search(cmd) or DOCKER_EXEC_ENV.search(cmd) or COMPOSE_CONFIG.search(cmd):
        deny(
            "Команда выведет окружение контейнера, а там токены ботов. Для inspect выбери "
            "конкретное поле через --format, для compose — `config -q` или `config --services`."
        )

    return 0


sys.exit(main())
