"""job_stats.py - job search statistics from production, over public HTTPS.

    python scripts/job_stats.py                 weekly stats (7 days), as a table
    python scripts/job_stats.py --days 30       any period, 1..180 days
    python scripts/job_stats.py review          vacancies waiting for a manual look
    python scripts/job_stats.py --json          raw JSON (works with `review` too)

Token: JOB_STATS_API_TOKEN from the environment, otherwise from
~/.zebaro/zebaro-core-bot-secrets.env. Base URL: PROD_URL (default https://bot.zebaro.dev).

The explicit User-Agent is not decoration: Cloudflare in front of the server answers 403
to urllib's default "Python-urllib/x.y".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SECRETS_FILE = Path.home() / ".zebaro" / "zebaro-core-bot-secrets.env"
USER_AGENT = "zebaro-job-stats/1.0"


def load_token() -> str:
    token = os.environ.get("JOB_STATS_API_TOKEN", "").strip()
    if token:
        return token
    if SECRETS_FILE.is_file():
        for line in reversed(SECRETS_FILE.read_text(encoding="utf-8").splitlines()):
            if line.startswith("JOB_STATS_API_TOKEN="):
                return line.split("=", 1)[1].strip().strip("\"'")
    sys.exit(f"Нет токена: задай JOB_STATS_API_TOKEN или положи его в {SECRETS_FILE}")


def fetch(path: str) -> Any:
    base = os.environ.get("PROD_URL", "https://bot.zebaro.dev").rstrip("/")
    request = urllib.request.Request(
        base + path,
        headers={"Authorization": f"Bearer {load_token()}", "User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 - fixed https base
            return json.load(response)
    except urllib.error.HTTPError as e:
        hints = {
            401: "токен не подошёл - сверь с секретом JOB_STATS_API_TOKEN в GitHub (env prod)",
            403: "ответил Cloudflare, до бота запрос не дошёл",
            422: "неверный параметр (--days от 1 до 180)",
        }
        sys.exit(f"HTTP {e.code} на {base + path}: {hints.get(e.code, e.reason)}")
    except urllib.error.URLError as e:
        sys.exit(f"Не достучался до {base}: {e.reason}")


def table(rows: list[list[Any]], headers: list[str]) -> str:
    cells = [headers] + [[str(c) for c in row] for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    lines = ["  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(row, widths))) for row in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def counter(title: str, data: dict[str, int], limit: int = 15) -> str:
    if not data:
        return f"{title}: -"
    items = list(data.items())[:limit]
    return f"{title}: " + ", ".join(f"{k} {v}" for k, v in items)


def print_weekly(stats: dict[str, Any]) -> None:
    t = stats["totals"]
    print(f"Период: {stats['period_days']} дн.")
    print(
        f"Найдено {t['found']} | отправлено {t['sent']} | на ревью {t['review']} | "
        f"отсеяно фильтром {t['rejected_by_filter']} | повторы {t['repeats']}"
    )
    print()
    keys = ["found", "sent", "review", "applied", "not_interested", "blocked", "clicks"]
    rows = [[p["platform"]] + [p.get(k, 0) for k in keys] for p in stats["by_platform"]]
    print(table(rows, ["platform"] + keys))
    print()
    print(counter("Статусы", stats["by_status"]))
    print(counter("Причины отсева", stats["by_reason"]))
    print(counter("Стек откликов", stats["stack_applied"]))
    print(counter("Стек отказов", stats["stack_rejected"]))
    rate = stats.get("response_rate")
    hours = stats.get("avg_hours_to_action")
    print(f"Доля откликов: {f'{rate:.0%}' if rate is not None else '-'}")
    print(f"Среднее время до действия: {f'{hours:.1f} ч' if hours is not None else '-'}")
    if stats.get("silent_sources"):
        print("Молчат источники: " + ", ".join(stats["silent_sources"]))


def print_review(jobs: list[dict[str, Any]]) -> None:
    if not jobs:
        print("На ревью пусто.")
        return
    for job in jobs:
        where = " - ".join(str(job[k]) for k in ("platform_name", "company") if job.get(k))
        print(f"* {job.get('title', '?')}" + (f"  [{where}]" if where else ""))
        if job.get("link"):
            print(f"  {job['link']}")
    print(f"\nВсего: {len(jobs)}")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Статистика поиска вакансий с прода")
    parser.add_argument("what", nargs="?", choices=["weekly", "review"], default="weekly")
    parser.add_argument("--days", type=int, default=7, help="период для weekly, 1..180")
    parser.add_argument("--json", action="store_true", help="сырой JSON вместо таблицы")
    args = parser.parse_args()

    data = fetch(f"/jobs/stats/weekly?days={args.days}" if args.what == "weekly" else "/jobs/review")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.what == "weekly":
        print_weekly(data)
    else:
        print_review(data)


if __name__ == "__main__":
    main()
