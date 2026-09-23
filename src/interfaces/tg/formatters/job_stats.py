import html
from typing import Any

_REASONS = {
    "senior": "senior (в заголовке или 5+ лет опыта)",
    "lead": "lead / head / architect",
    "intern": "стажировка / trainee",
    "junior": "junior (старое правило, джунов теперь берём)",
    "not a developer role": "не разработка (QA, менеджеры, дизайн…)",
    "company": "ФОП / школа",
    "location": "другой континент (Индия и т.п.)",
    "stale": "висит на сайте больше двух месяцев",
    "no stack match": "стек не совпал",
}

# How many technologies the "what you answer to" lists show before it stops being readable.
_TOP_STACK = 6


def _stack_line(counter: dict[str, int]) -> str:
    items = list(counter.items())[:_TOP_STACK]
    return ", ".join(f"{html.escape(name)} <b>{count}</b>" for name, count in items)


def format_weekly_digest_rich(stats: dict[str, Any]) -> str:
    """The digest as a rich message: tables instead of lines of "label: number"."""
    totals = stats["totals"]
    by_status = stats["by_status"]

    parts = [
        f"<h2>📊 Вакансии за {stats['period_days']} дней</h2>",
        "<table bordered striped compact>"
        "<tr><th>Найдено</th><th>🔥 Твой стек</th><th>👀 Частично</th><th>Мимо</th></tr>"
        f"<tr><td align=\"center\">{totals['found']}</td><td align=\"center\">{totals['sent']}</td>"
        f"<td align=\"center\">{totals['review']}</td><td align=\"center\">{totals['rejected_by_filter']}</td></tr>"
        "</table>",
        "<h4>Что ты с ними сделал</h4>",
        "<ul>"
        f"<li>✅ Откликнулся — <b>{by_status['applied']}</b></li>"
        f"<li>❌ Не интересует — <b>{by_status['not_interested']}</b></li>"
        f"<li>⏳ Без реакции — <b>{by_status['pending']}</b></li>"
        "</ul>",
    ]

    facts = []
    if stats["response_rate"] is not None:
        facts.append(f"откликаешься на <b>{stats['response_rate']:.0%}</b> присланного")
    if stats["avg_hours_to_action"] is not None:
        facts.append(f"реагируешь в среднем за <b>{stats['avg_hours_to_action']:.1f} ч</b>")
    if facts:
        sentence = ", ".join(facts)
        parts.append(f"<p>{sentence[0].upper()}{sentence[1:]}</p>")

    if stats["by_platform"]:
        rows = "".join(
            f"<tr><td>{html.escape(p['platform'])}</td><td align=\"center\">{p['found']}</td>"
            f"<td align=\"center\">{p['sent']}</td><td align=\"center\">{p.get('review', 0)}</td>"
            f"<td align=\"center\">{p['applied']}</td><td align=\"center\">{p['not_interested']}</td></tr>"
            for p in stats["by_platform"]
        )
        parts.append(
            "<h4>По площадкам</h4><table bordered striped compact>"
            "<tr><th>Площадка</th><th>Всего</th><th>🔥</th><th>👀</th><th>✅</th><th>❌</th></tr>" + rows + "</table>"
        )

    # What the owner answers to, against what he waves off: the two lists are the evidence
    # for every change to the filter's stack.
    applied, rejected = stats.get("stack_applied") or {}, stats.get("stack_rejected") or {}
    if applied or rejected:
        parts.append("<h4>На что ты откликаешься</h4><ul>")
        if applied:
            parts.append(f"<li>✅ {_stack_line(applied)}</li>")
        if rejected:
            parts.append(f"<li>❌ {_stack_line(rejected)}</li>")
        parts.append("</ul>")

    by_reason = stats.get("by_reason") or {}
    if by_reason:
        items = "".join(
            f"<li>{html.escape(_REASONS.get(reason, reason))} — <b>{count}</b></li>"
            for reason, count in by_reason.items()
        )
        parts.append(f"<h4>Почему не прислал</h4><ul>{items}</ul>")

    silent = stats.get("silent_sources") or []
    if silent:
        names = ", ".join(html.escape(name) for name in silent)
        parts.append(f"<p>⚠️ Ничего не дали за период: <b>{names}</b> — или блокируют, или сломалась вёрстка.</p>")

    return "".join(parts)


def format_weekly_digest(stats: dict[str, Any]) -> str:
    """Plain HTML fallback for when Telegram refuses the rich message."""
    totals = stats["totals"]
    by_status = stats["by_status"]

    text = f"<b>📊 Джоб-дайджест за {stats['period_days']} дней</b>\n\n"
    text += (
        f"Найдено: <b>{totals['found']}</b>\n"
        f"🔥 Отправлено: <b>{totals['sent']}</b>\n"
        f"👀 Частично: <b>{totals['review']}</b>\n"
        f"Отфильтровано: <b>{totals['rejected_by_filter']}</b>\n\n"
        f"✅ Откликнулся: <b>{by_status['applied']}</b>\n"
        f"❌ Не интересует: <b>{by_status['not_interested']}</b>\n"
        f"⏳ Без реакции: <b>{by_status['pending']}</b>\n"
    )

    response_rate = stats["response_rate"]
    if response_rate is not None:
        text += f"\nResponse rate: <b>{response_rate:.0%}</b>"

    avg_hours = stats["avg_hours_to_action"]
    if avg_hours is not None:
        text += f"\nСреднее время реакции: <b>{avg_hours:.1f} ч</b>"

    by_platform = stats["by_platform"]
    if by_platform:
        text += "\n\n<b>По площадкам:</b>\n"
        for platform_stats in by_platform:
            text += (
                f"• {html.escape(platform_stats['platform'])}: "
                f"найдено {platform_stats['found']}, "
                f"отправлено {platform_stats['sent']}, "
                f"откликнулся {platform_stats['applied']}\n"
            )

    silent = stats.get("silent_sources") or []
    if silent:
        text += f"\n⚠️ Ничего не дали: {html.escape(', '.join(silent))}"

    return text
