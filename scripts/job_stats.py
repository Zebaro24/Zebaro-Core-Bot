"""job_stats.py - job search statistics from production, over public HTTPS.

    python scripts/job_stats.py                 weekly stats (7 days), as a table
    python scripts/job_stats.py --days 30       any period, 1..180 days
    python scripts/job_stats.py review          vacancies waiting for a manual look
    python scripts/job_stats.py job <id>        one vacancy in full: our _id or the platform's job_id
    python scripts/job_stats.py search [text] --platform dou --moderation review --status applied
                                --reason senior --days 30 --limit 50
    python scripts/job_stats.py applied --days 90 --out applied.md
                                vacancies you applied to, with descriptions - ready for an AI
    (search takes --full too: the same blocks with descriptions instead of a table;
     --status-reason experience and --search-url djinni narrow it further)
    python scripts/job_stats.py searches --days 30   every search URL: found, sent, answered
    python scripts/job_stats.py digest --days 7      the weekly digest's numbers
    python scripts/job_stats.py audit --days 30      your "no" answers grouped by reason: where the
                                filter let through what it should have caught
    python scripts/job_stats.py fields --days 7      what the parsers read off each vacancy: format,
                                countries, years, English, salary, applicants, warnings
    poetry run python scripts/job_stats.py replay --days 60
                                the filter of this working tree over the stored vacancies, against
                                your answers: what it would now skip that you applied to
    python scripts/job_stats.py --json          raw JSON (works with every command)

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
import urllib.parse
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
        with urllib.request.urlopen(request, timeout=30) as response:  # fixed https base
            return json.load(response)
    except urllib.error.HTTPError as e:
        hints = {
            401: "токен не подошёл - сверь с секретом JOB_STATS_API_TOKEN в GitHub (env prod)",
            403: "ответил Cloudflare, до бота запрос не дошёл",
            404: "не найдено (или на проде старая версия без этого эндпоинта)",
            422: "неверный параметр (--days, --limit вне допустимого)",
        }
        sys.exit(f"HTTP {e.code} на {base + path}: {hints.get(e.code, e.reason)}")
    except urllib.error.URLError as e:
        sys.exit(f"Не достучался до {base}: {e.reason}")


def fetch_all(params: dict[str, Any], cap: int = 5000) -> list[dict[str, Any]]:
    """Every vacancy the search matches, 500 at a time (the API's page size)."""
    docs: list[dict[str, Any]] = []
    while len(docs) < cap:
        page = fetch("/jobs/search?" + urllib.parse.urlencode({**params, "limit": 500, "skip": len(docs)}))
        docs += page
        if len(page) < 500:
            break
    return docs


def table(rows: list[list[Any]], headers: list[str]) -> str:
    cells = [headers] + [[str(c) for c in row] for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    lines = [
        "  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(row, widths, strict=True)))
        for row in cells
    ]
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
    print(table(rows, ["platform", *keys]))
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


def print_job(job: dict[str, Any]) -> None:
    skip = {"description", "copies"}
    width = max(len(k) for k in job)
    for key, value in job.items():
        if key not in skip and value not in (None, "", [], {}):
            print(f"{key.ljust(width)}  {value}")
    if job.get("copies"):
        print(f"{'copies'.ljust(width)}  {len(job['copies'])}")
    if job.get("description"):
        print("\n" + str(job["description"]).strip())


def print_search(jobs: list[dict[str, Any]]) -> None:
    rows = [
        [
            str(j.get("found_at", ""))[:10],
            j.get("platform_name", ""),
            j.get("moderation", ""),
            j.get("user_status", ""),
            j.get("relevance_score", ""),
            j.get("click_count", 0),
            str(j.get("title", ""))[:50],
            str(j.get("company", ""))[:25],
            j.get("_id", ""),
        ]
        for j in jobs
    ]
    print(table(rows, ["found", "platform", "moderation", "status", "score", "clicks", "title", "company", "id"]))
    print(f"\nВсего: {len(jobs)}")


def render_full(jobs: list[dict[str, Any]]) -> str:
    """Markdown blocks with descriptions: a file an AI can read and compare as is."""
    blocks = []
    for j in jobs:
        facts = [
            f"- Платформа: {j.get('platform_name', '?')}, найдено {str(j.get('found_at', ''))[:10]}",
            f"- Модерация: {j.get('moderation', '?')}, статус: {j.get('user_status', '?')}, "
            f"score {j.get('relevance_score', '?')}, кликов {j.get('click_count', 0)}",
        ]
        for key, label in (
            ("matched_stack", "Стек"),
            ("matched_bonus", "Бонусы"),
            ("required_years", "Опыт, лет"),
            ("location", "Локация"),
            ("filter_reason", "Причина отсева"),
        ):
            if j.get(key) not in (None, "", []):
                value = ", ".join(map(str, j[key])) if isinstance(j[key], list) else j[key]
                facts.append(f"- {label}: {value}")
        facts.append(f"- Ссылка: {j.get('link', '')}  (id {j.get('_id', '')})")
        description = str(j.get("description") or "(описания нет)").strip()
        header = f"## {j.get('title', '?')} - {j.get('company', '?')}"
        blocks.append(header + "\n\n" + "\n".join(facts) + "\n\n" + description)
    return f"# Вакансии: {len(jobs)}\n\n" + "\n\n---\n\n".join(blocks) + "\n"


def print_searches(rows: list[dict[str, Any]]) -> None:
    def rate(row: dict[str, Any]) -> str:
        return f"{row['apply_rate']:.0%}" if row.get("apply_rate") is not None else "-"

    data = [
        [r["label"][:45], r["found"], r["surfaced"], r["top"], r["applied"], r["mismatch"], r["not_interested"],
         r["pending"], rate(r), ", ".join(f"{k} {v}" for k, v in list(r["reasons"].items())[:3])]
        for r in rows
    ]  # fmt: skip
    print(table(data, ["search", "found", "sent", "top", "appl", "mism", "ni", "pend", "rate", "filtered out"]))


def print_digest(digest: dict[str, Any]) -> None:
    print(json.dumps(digest, ensure_ascii=False, indent=2))


def print_audit(jobs: list[dict[str, Any]]) -> None:
    """Answers grouped by their reason: each group is a rule the filter could learn."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for j in jobs:
        blocked = j.get("user_status") == "blocked"
        status = "mismatch" if blocked else j.get("user_status")
        reason = "site" if blocked else j.get("status_reason") or "-"
        groups.setdefault(f"{status} / {reason}", []).append(j)
    for key, items in sorted(groups.items(), key=lambda item: -len(item[1])):
        print(f"\n== {key}: {len(items)}")
        for j in items[:25]:
            facts = " ".join(
                f"{k}={j[k]}" for k in ("moderation", "required_years", "english", "work_format", "countries")
                if j.get(k) not in (None, "", [])
            )  # fmt: skip
            print(f"  {str(j.get('title', ''))[:55]:55}  {str(j.get('platform_name', ''))[:8]:8}  {facts}")


def print_fields(jobs: list[dict[str, Any]]) -> None:
    rows = [
        [str(j.get("title", ""))[:40], str(j.get("platform_name", ""))[:8], str(j.get("moderation", ""))[:6],
         j.get("work_format") or "", str(j.get("countries") or "")[:20], j.get("required_years") or "",
         j.get("english") or "", str(j.get("salary") or "")[:14], j.get("applicants") or "",
         ",".join(j.get("warnings") or []), j.get("filter_reason") or ""]
        for j in jobs
    ]  # fmt: skip
    headers = ["title", "platform", "mod", "format", "countries", "yrs", "eng", "salary", "appl", "warnings", "reason"]
    print(table(rows, headers))


def replay(days: int) -> None:
    """Run the filter of this working tree over the stored vacancies and compare with the answers.

    Needs the project's environment (poetry run): it imports src/. Nothing is written anywhere.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from src.services.job_searcher.container import Job
        from src.services.job_searcher.filter import evaluate
    except ImportError as e:
        sys.exit(f"replay imports src/ - run it as `poetry run python scripts/job_stats.py replay` ({e})")

    docs = fetch_all({"days": days, "with_description": "true"})
    counts: dict[tuple[str, str], int] = {}
    lost: list[tuple[str | None, dict[str, Any]]] = []
    caught = 0
    for doc in docs:
        status = doc.get("user_status") or "pending"
        # Staleness is about today, not the day the vacancy was found.
        # Years and English stored by an older filter came from the text: read them again. Only
        # Djinni's are the card's own.
        fresh = {} if doc.get("platform_name") == "Djinni" else {"required_years": None, "english": None}
        verdict = evaluate(Job.from_doc({**doc, "date": None, **fresh}))
        counts[(status, verdict.moderation)] = counts.get((status, verdict.moderation), 0) + 1
        if status == "applied" and verdict.moderation == "rejected_by_filter":
            lost.append((verdict.reason, doc))
        if status in ("not_interested", "mismatch", "blocked") and verdict.moderation == "rejected_by_filter":
            caught += 1

    print(f"Вакансий: {len(docs)} за {days} дн.\n")
    tiers = ["top", "sent", "review", "rejected_by_filter"]
    statuses = sorted({status for status, _ in counts})
    print(table([[s] + [counts.get((s, t), 0) for t in tiers] for s in statuses], ["status", *tiers]))
    print(f"\nОтказов, которые фильтр теперь отсеял бы сам: {caught}")
    print(f"Откликов, которые фильтр теперь отсеял бы: {len(lost)}")
    for reason, doc in lost:
        print(f"  [{reason}] {doc.get('title')} - {doc.get('company')}  ({doc.get('_id')})")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Статистика и данные поиска вакансий с прода")
    parser.add_argument("--json", action="store_true", help="сырой JSON вместо таблицы")
    parser.add_argument("--days", type=int, help="период: weekly 1..180 (7), search 1..365 (30), applied (90)")
    # The same flags after the subcommand; SUPPRESS keeps a subparser from resetting them.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--days", type=int, default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="what")
    sub.add_parser("weekly", parents=[common], help="недельная статистика (по умолчанию)")
    sub.add_parser("review", parents=[common], help="вакансии на ручном ревью")
    job = sub.add_parser("job", parents=[common], help="одна вакансия целиком")
    job.add_argument("id")
    search = sub.add_parser("search", parents=[common], help="поиск вакансий")
    search.add_argument("text", nargs="?", help="подстрока в названии или компании")
    search.add_argument("--platform")
    search.add_argument("--moderation", help="sent / review / rejected_by_filter")
    search.add_argument("--status", help="pending / applied / not_interested / blocked")
    search.add_argument("--reason", help="подстрока причины отсева")
    search.add_argument("--status-reason", help="experience / location / english / site / stack / role / ...")
    search.add_argument("--search-url", help="подстрока URL поиска, который нашёл вакансию")
    applied = sub.add_parser("applied", parents=[common], help="отклики с описаниями - для анализа ИИ")
    sub.add_parser("searches", parents=[common], help="статистика по каждому URL поиска")
    sub.add_parser("digest", parents=[common], help="цифры недельного дайджеста")
    sub.add_parser("audit", parents=[common], help="ответы «не прохожу» / «не интересно» по причинам")
    sub.add_parser("fields", parents=[common], help="что парсеры вытащили из вакансий")
    sub.add_parser("replay", parents=[common], help="фильтр из рабочей копии против твоих ответов")
    for p in (search, applied):
        p.add_argument("--limit", type=int, default=50)
        p.add_argument("--full", action="store_true", help="блоками с описаниями, а не таблицей")
        p.add_argument("--out", help="записать результат в файл (markdown)")
    args = parser.parse_args()
    what = args.what or "weekly"

    if what == "weekly":
        data = fetch(f"/jobs/stats/weekly?days={args.days or 7}")
    elif what == "review":
        data = fetch("/jobs/review")
    elif what == "job":
        data = fetch("/jobs/job/" + urllib.parse.quote(args.id, safe=""))
    elif what == "searches":
        data = fetch(f"/jobs/stats/searches?days={args.days or 30}")
    elif what == "digest":
        data = fetch(f"/jobs/stats/digest?days={args.days or 7}")
    elif what == "audit":
        data = [
            doc
            for status in ("mismatch", "blocked", "not_interested")
            for doc in fetch_all({"days": args.days or 30, "status": status})
        ]
    elif what == "fields":
        data = fetch_all({"days": args.days or 7})
    elif what == "replay":
        replay(args.days or 60)
        return
    elif what in ("search", "applied"):
        full = what == "applied" or args.full
        params = {
            "q": getattr(args, "text", None),
            "platform": getattr(args, "platform", None),
            "moderation": getattr(args, "moderation", None),
            "status": "applied" if what == "applied" else args.status,
            "reason": getattr(args, "reason", None),
            "status_reason": getattr(args, "status_reason", None),
            "search_url": getattr(args, "search_url", None),
            "days": args.days or (90 if what == "applied" else 30),
            "limit": args.limit,
            "with_description": "true" if full else None,
        }
        data = fetch("/jobs/search?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}))
        if not args.json:
            text = render_full(data) if full else None
            if args.out:
                Path(args.out).write_text(text or json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Записал {len(data)} вакансий в {args.out}")
            elif text:
                print(text)
            else:
                print_search(data)
            return

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        printers = {
            "weekly": print_weekly, "review": print_review, "job": print_job, "searches": print_searches,
            "digest": print_digest, "audit": print_audit, "fields": print_fields,
        }  # fmt: skip
        printers[what](data)


if __name__ == "__main__":
    main()
