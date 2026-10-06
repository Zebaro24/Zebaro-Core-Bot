"""The weekly digest in Telegram: "the market" and "your week" (services/job_searcher/digest.py)."""

import html
from typing import Any

# Why the filter did not send a vacancy. Old reasons stay: the API reports stored documents.
REASONS = {
    "senior": "senior в названии или в описании",
    "experience": "просят от 4 лет",
    "english": "английский выше B2",
    "lead": "lead / head / architect",
    "intern": "стажировка / trainee",
    "junior": "junior (старое правило)",
    "not a developer role": "не разработка",
    "other stack": "другой основной стек",
    "office": "офис или гибрид",
    "country": "не берут из-за границы",
    "company": "ФОП / школа",
    "military": "воинская часть",
    "location": "другой континент",
    "stale": "висит больше двух месяцев",
    "no stack match": "стек не совпал",
}
MISMATCH_REASONS = {
    "experience": "опыт",
    "location": "офис / страна",
    "english": "английский",
    "stack": "стек",
    "site": "сайт не пустил",
    "other": "другое",
}
REJECT_REASONS = {"role": "роль", "stack": "стек", "domain": "домен", "conditions": "условия", "other": "просто нет"}
_FORMATS = {"remote": "удалённо", "office_or_remote": "офис или удалённо", "hybrid": "гибрид", "office": "офис"}


def _pct(value: float | None) -> str:
    return f"{value:.0%}" if value is not None else "—"


def _trend(now: int, before: int) -> str:
    if now == before:
        return ""
    return f" ▲{now - before}" if now > before else f" ▼{before - now}"


def _shares(counter: dict[str, int], names: dict[str, str] | None = None) -> str:
    total = sum(counter.values())
    if not total:
        return "—"
    return " · ".join(f"{html.escape((names or {}).get(k, k))} {v / total:.0%}" for k, v in counter.items())


def _cells(counter: dict[str, Any]) -> str:
    return "".join(f'<td align="center">{v}</td>' for v in counter.values())


def _heads(counter: dict[str, Any]) -> str:
    return "".join(f"<th>{html.escape(str(k))}</th>" for k in counter)


def format_market_rich(digest: dict[str, Any]) -> str:
    market = digest["market"]
    tiers = market["by_tier"]
    parts = [
        f"<h2>🌍 Рынок за {digest['period_days']} дней</h2>",
        f"<p>В твоей области <b>{market['in_field']}</b> вакансий, прислал <b>{market['surfaced']}</b>: "
        f"🔥🔥🔥 {tiers['top']} · 🔥 {tiers['sent']} · 👀 {tiers['review']}</p>",
        "<h4>Сколько лет опыта просят</h4>",
        f"<table bordered compact><tr>{_heads(market['years'])}</tr><tr>{_cells(market['years'])}</tr></table>",
        "<h4>Какой английский</h4>",
        f"<table bordered compact><tr>{_heads(market['english'])}</tr><tr>{_cells(market['english'])}</tr></table>",
    ]
    if market["english_b1_share"] is not None:
        parts.append(f"<p>Где уровень назван, B1 хватает в <mark>{_pct(market['english_b1_share'])}</mark></p>")
    if market["work_format"]:
        parts.append(f"<p>📍 Формат: {_shares(market['work_format'], _FORMATS)}</p>")
    if market["top_tech"]:
        tech = " · ".join(f"{html.escape(name)} {share:.0%}" for name, share in market["top_tech"])
        parts.append(f"<h4>Чаще всего просят</h4><p>{tech}</p>")
    if salary := market["salary"]:
        parts.append(
            f"<p>💰 Зарплата: медиана <b>${salary['median']}</b>, от ${salary['low']} до ${salary['high']} "
            f"(по {salary['n']} вакансиям)</p>"
        )
    if market["applicants_median"] is not None:
        parts.append(f"<p>👥 На вакансию Djinni откликаются в среднем <b>{market['applicants_median']}</b> человек</p>")
    if market["blockers"]:
        items = "".join(
            f"<li>{html.escape(REASONS.get(reason, reason))} — <b>{count}</b></li>"
            for reason, count in market["blockers"].items()
        )
        parts.append(f"<h4>Что не пускает в твою область</h4><ul>{items}</ul>")
    return "".join(parts)


def format_me_rich(digest: dict[str, Any]) -> str:
    me = digest["me"]
    now, before = me["decisions"], me["prev"]
    parts = [
        "<h2>👤 Твоя неделя</h2>",
        "<table bordered striped compact><tr><th>✅ Отклик</th><th>🚫 Не прохожу</th><th>👎 Не интересно</th>"
        "<th>⛔ Не пустил</th></tr><tr>"
        + "".join(
            f'<td align="center">{now[k]}{_trend(now[k], before[k])}</td>'
            for k in ("applied", "mismatch", "not_interested", "blocked")
        )
        + "</tr></table>",
        f"<p>Откликаешься на <b>{_pct(me['apply_rate'])}</b> решений (неделей раньше {_pct(me['apply_rate_prev'])})"
        + (f", реагируешь за {me['avg_hours_to_action']:.0f} ч" if me["avg_hours_to_action"] is not None else "")
        + "</p>",
    ]
    pending = me["pending"]
    if pending["count"]:
        old = f", из них {pending['old']} старше 3 дней" if pending["old"] else ""
        parts.append(f"<p>⏳ Ждут ответа: <b>{pending['count']}</b>{old}</p>")

    if me["by_platform"]:
        rows = "".join(
            f'<tr><td>{html.escape(p["platform"])}</td><td align="center">{p["decided"]}</td>'
            f'<td align="center">{p["applied"]}</td><td align="center">{_pct(p["rate"])}</td>'
            f'<td align="center">{p["blocked"] or ""}</td></tr>'
            for p in me["by_platform"]
        )
        parts.append(
            "<h4>Площадки</h4><table bordered striped compact>"
            "<tr><th>Площадка</th><th>Решений</th><th>✅</th><th>%</th><th>⛔</th></tr>" + rows + "</table>"
        )
    tiers = me["by_tier_rate"]
    if any(rate is not None for rate in tiers.values()):
        parts.append(
            f"<p>Откликаешься по тирам (4 недели): 🔥🔥🔥 {_pct(tiers['top'])} · 🔥 {_pct(tiers['sent'])} · "
            f"👀 {_pct(tiers['review'])}</p>"
        )
    if searches := me["searches"]:
        best = " · ".join(f"{html.escape(s['label'])} {s['rate']:.0%} ({s['n']})" for s in searches["best"])
        worst = " · ".join(f"{html.escape(s['label'])} {s['rate']:.0%} ({s['n']})" for s in searches["worst"])
        parts.append(f"<h4>Поиски за 4 недели</h4><p>👍 {best}<br>👎 {worst}</p>")
    if me["mismatch_reasons"]:
        years = me["mismatch_years_median"]
        line = _shares(me["mismatch_reasons"], MISMATCH_REASONS)
        parts.append(
            f"<h4>Чего не хватает</h4><p>{line}"
            + (f"<br>В таких вакансиях просят в среднем {years} г. опыта" if years else "")
            + "</p>"
        )
    if (misses := me["filter_misses"]) and misses["mismatch"]:
        parts.append(
            f"<p>⚠️ Фильтр ошибся: из {misses['promised']} 🔥 ты не прошёл по <b>{misses['mismatch']}</b> — "
            "причины выше, их стоит научить фильтр видеть</p>"
        )
    if me["not_interested_reasons"]:
        parts.append(f"<p>👎 Не интересно: {_shares(me['not_interested_reasons'], REJECT_REASONS)}</p>")
    silent = digest.get("silent_sources") or []
    if silent:
        names = ", ".join(html.escape(name) for name in silent)
        parts.append(f"<p>⚠️ Ничего не дали за период: <b>{names}</b> — или блокируют, или сломалась вёрстка.</p>")
    return "".join(parts)


def format_digest_plain(digest: dict[str, Any]) -> str:
    """Plain HTML fallback for when Telegram refuses the rich messages: the key numbers only."""
    market, me = digest["market"], digest["me"]
    now = me["decisions"]
    years = " · ".join(f"{k} {v}" for k, v in market["years"].items())
    english = " · ".join(f"{k} {v}" for k, v in market["english"].items())
    platforms = "\n".join(
        f"• {html.escape(p['platform'])}: {p['decided']} решений, ✅ {p['applied']} ({_pct(p['rate'])})"
        for p in me["by_platform"]
    )
    text = (
        f"<b>📊 Вакансии за {digest['period_days']} дней</b>\n\n"
        f"🌍 В твоей области {market['in_field']}, прислал {market['surfaced']}\n"
        f"Опыт: {years}\nАнглийский: {html.escape(english)}\n\n"
        f"✅ {now['applied']} · 🚫 {now['mismatch']} · 👎 {now['not_interested']} · ⛔ {now['blocked']}\n"
        f"Откликаешься на {_pct(me['apply_rate'])}\n"
    )
    if platforms:
        text += f"\n{platforms}"
    return text
