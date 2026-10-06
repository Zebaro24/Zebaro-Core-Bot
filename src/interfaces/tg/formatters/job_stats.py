"""The weekly digest in Telegram: "who the companies look for" and "your applications".

services/job_searcher/digest.py computes everything; here it is laid out as a rich message:
a row of key figures, bar charts in <pre> (monospace keeps the bars aligned), a mark where
the owner stands, and the insights in words.
"""

import html
from datetime import datetime
from typing import Any

# Why the filter did not send a vacancy. Old reasons stay: the API reports stored documents.
REASONS = {
    "senior": "senior в названии/тексте",
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
_FORMATS = {"remote": "удалённо", "office_or_remote": "офис / удалённо", "hybrid": "гибрид", "office": "офис"}
# Words, not the fire emoji: inside <pre> one, two or three emoji break the column of bars.
_TIERS = {"top": "в яблочко", "sent": "твой стек", "review": "частично"}

_BAR = 12
_YOU = "  ← ты"


def _pct(value: float | None) -> str:
    return f"{value:.0%}" if value is not None else "—"


def _bar(share: float, cells: int = _BAR) -> str:
    filled = max(0, min(cells, round(share * cells)))
    if share > 0 and filled == 0:
        filled = 1  # a thin sliver: "some", not "none"
    return "█" * filled + "░" * (cells - filled)


def _chart(rows: list[tuple[str, float, str]], mark: str | None = None) -> str:
    """Bars in a monospace block: label, bar, figure — and "← ты" on the owner's row."""
    width = max((len(label) for label, _, _ in rows), default=0)
    lines = [
        f"{label.ljust(width)} {_bar(share)} {figure}{_YOU if label == mark else ''}" for label, share, figure in rows
    ]
    return "<pre>" + html.escape("\n".join(lines)) + "</pre>"


def _arrow(delta: float | None) -> str:
    if delta is None:
        return ""
    if delta >= 0.08:
        return " ↑"
    if delta <= -0.08:
        return " ↓"
    return ""


def _trend(now: int, before: int | None) -> str:
    if not before or now == before:
        return ""
    change = now / before - 1
    return f" {'▲' if change > 0 else '▼'}{abs(change):.0%}"


def _period(digest: dict[str, Any]) -> str:
    since, until = digest.get("since"), digest.get("until")
    if isinstance(since, datetime) and isinstance(until, datetime):
        return f"{since:%d.%m} — {until:%d.%m.%Y}"
    return f"за {digest['period_days']} дней"


def _kpis(cells: list[tuple[str, str]]) -> str:
    heads = "".join(f"<th>{title}</th>" for title, _ in cells)
    values = "".join(f'<td align="center"><b>{value}</b></td>' for _, value in cells)
    return f"<table bordered compact><tr>{heads}</tr><tr>{values}</tr></table>"


def _bucket_chart(counter: dict[str, int], labels: dict[str, str], mark: str) -> str:
    known = {key: count for key, count in counter.items() if key != "?"}
    total = sum(known.values())
    if not total:
        return "<p><i>Пока не указывают</i></p>"
    rows = [(labels.get(key, key), count / total, f"{count / total:>4.0%}") for key, count in known.items()]
    chart = _chart(rows, mark=labels.get(mark, mark))
    if counter.get("?"):
        chart += f"<p><i>Не указано ещё в {counter['?']}</i></p>"
    return chart


# --- the market ----------------------------------------------------------------------------


def _market_insight(item: dict[str, Any]) -> str:
    kind = item["kind"]
    if kind == "seniority_wall":
        return (
            f"🧱 Главная стена — уровень: <b>{_pct(item['share'])}</b> вакансий твоей области ({item['count']}) "
            "ищут senior, lead или 4+ лет."
        )
    if kind == "english_gate":
        return (
            f"🗣 Где уровень назван, твоего B1 хватает в <b>{_pct(item['b1_share'])}</b>. B2 открыл бы ещё "
            f"<b>{item['b2_count']}</b> вакансий за неделю — самый дешёвый рычаг."
        )
    if kind == "tech_rising":
        return f"📈 Чаще стали просить: <b>{html.escape(', '.join(item['names']))}</b>."
    if kind == "tech_falling":
        return f"📉 Реже стали просить: {html.escape(', '.join(item['names']))}."
    if kind == "volume":
        word = "больше" if item["change"] > 0 else "меньше"
        return f"📦 Вакансий на <b>{abs(item['change']):.0%} {word}</b>, чем неделей раньше."
    if kind == "competition":
        return (
            f"👥 На вакансию Djinni в среднем <b>{item['median']}</b> откликов — сильное резюме и быстрый ответ "
            "решают больше, чем количество."
        )
    return ""


def format_market_rich(digest: dict[str, Any]) -> str:
    market = digest["market"]
    tiers = market["by_tier"]
    salary = market["salary"]
    applicants = market["applicants"]
    parts = [
        "<h2>🌍 Кого ищут компании</h2>",
        f"<p><i>{_period(digest)} · вакансии твоей области: Python, React, AI</i></p>",
        _kpis(
            [
                ("📦 Вакансий", f"{market['in_field']}{_trend(market['in_field'], market['in_field_prev'])}"),
                ("🎯 Подходят тебе", f"{market['surfaced']} · {_pct(market['reach_share'])}"),
                ("💰 Медиана", f"${salary['median']}" if salary else "—"),
                ("👥 Откликов", str(applicants["median"]) if applicants else "—"),
            ]
        ),
        f"<p>Прислал: 🔥🔥🔥 <b>{tiers['top']}</b> · 🔥 <b>{tiers['sent']}</b> · 👀 <b>{tiers['review']}</b></p>",
        "<h4>🎓 Сколько опыта просят</h4>",
        _bucket_chart(market["years"], {"≤1": "до 1 г", "2": "2 г", "3": "3 г", "4+": "4+ л"}, "3"),
        "<h4>🗣 Какой английский</h4>",
        _bucket_chart(market["english"], {"≤B1": "до B1", "B2": "B2", "C1+": "C1+"}, "≤B1"),
    ]
    if market["top_tech"]:
        rows = [
            (tech["name"], tech["share"], f"{tech['share']:>4.0%}{_arrow(tech['delta'])}")
            for tech in market["top_tech"]
        ]
        parts += ["<h4>🧰 Что просят чаще всего</h4>", _chart(rows)]
    if market["work_format"]:
        total = sum(market["work_format"].values())
        line = " · ".join(f"{_FORMATS.get(k, k)} {v / total:.0%}" for k, v in market["work_format"].items())
        parts.append(f"<p>📍 Формат: {html.escape(line)}</p>")
    if salary:
        parts.append(
            f"<p>💰 Зарплаты: медиана <b>${salary['median']}</b>, половина вакансий — от ${salary['low']} "
            f"до ${salary['high']} (по {salary['n']} с вилкой)</p>"
        )
    if market["blockers"]:
        total = market["in_field"] or 1
        rows = [
            (REASONS.get(reason, reason), count / total, f"{count:>3}") for reason, count in market["blockers"].items()
        ]
        parts += ["<h4>🚧 Что отсекает тебя</h4>", _chart(rows)]
    insights = [text for item in digest.get("market_insights") or [] if (text := _market_insight(item))]
    if insights:
        parts.append("<h4>💡 Выводы</h4><ul>" + "".join(f"<li>{text}</li>" for text in insights) + "</ul>")
    parts.append(f"<footer>Из {market['in_field']} вакансий твоей области за неделю, без повторов</footer>")
    return "".join(parts)


# --- the owner -----------------------------------------------------------------------------


def _my_insight(item: dict[str, Any]) -> str:
    kind = item["kind"]
    if kind == "platform_gap":
        blocked = f", ещё {item['worst_blocked']} раз сайт не пустил" if item["worst_blocked"] else ""
        return (
            f"🏆 Лучше всего у тебя на <b>{html.escape(item['best'])}</b> — {_pct(item['best_rate'])} откликов; "
            f"на {html.escape(item['worst'])} — {_pct(item['worst_rate'])}{blocked}."
        )
    if kind == "tiers":
        if item["top"] - item["review"] >= 0.15:
            return (
                f"🎯 Тиры работают: на 🔥🔥🔥 откликаешься в <b>{_pct(item['top'])}</b> случаев, на 👀 — в "
                f"{_pct(item['review'])}. 👀 можно разбирать пачкой раз в день."
            )
        return (
            f"🎯 Тиры почти не различаются ({_pct(item['top'])} против {_pct(item['review'])}) — "
            "отмечай причины у «нет», фильтр по ним подстроится."
        )
    if kind == "main_gap":
        reason = html.escape(MISMATCH_REASONS.get(item["reason"], str(item["reason"])))
        years = f" (просят в среднем {item['years']} г.)" if item["reason"] == "experience" and item["years"] else ""
        return f"🧩 Чаще всего не проходишь по пункту «<b>{reason}</b>» — {_pct(item['share'])}{years}."
    if kind == "filter_miss":
        reason = MISMATCH_REASONS.get(item["reason"] or "", "")
        why = f", чаще всего — {reason}" if reason else ""
        return f"🔧 Фильтр {item['count']} раз из {item['of']} прислал 🔥 не по требованиям{why}. Можно ужесточить."
    if kind == "speed":
        return (
            f"⏱ Отвечаешь в среднем через <b>{item['hours']:.0f} ч</b>, а на вакансию Djinni за это время набегает "
            f"~{item['applicants']} откликов. На 🔥🔥🔥 — в тот же день."
        )
    if kind == "backlog":
        return f"⏳ {item['old']} вакансий ждут ответа дольше 3 дней — разбери или пропусти: их могли уже закрыть."
    if kind == "dead_search":
        labels = html.escape(", ".join(item["labels"]))
        return f"🗑 Поиски без единого отклика за 4 недели: {labels} — кандидаты на удаление."
    if kind == "trend":
        word = "больше" if item["now"] > item["before"] else "меньше"
        market = item["market_change"]
        context = ""
        if market is not None and abs(market) >= 0.1:
            context = f" — и вакансий на рынке на {abs(market):.0%} {'больше' if market > 0 else 'меньше'}"
        return f"📊 Откликов {word}, чем неделей раньше: {item['now']} против {item['before']}{context}."
    return ""


def format_me_rich(digest: dict[str, Any]) -> str:
    me = digest["me"]
    now, before = me["decisions"], me["prev"]
    hours = me["avg_hours_to_action"]
    parts = [
        "<h2>👤 Твои отклики</h2>",
        f"<p><i>{_period(digest)}</i></p>",
        _kpis(
            [
                ("✅ Откликов", f"{now['applied']}{_trend(now['applied'], before['applied'])}"),
                ("🎯 От решений", _pct(me["apply_rate"])),
                ("⏱ Реакция", f"{hours:.0f} ч" if hours is not None else "—"),
                ("⏳ Ждут", str(me["pending"]["count"])),
            ]
        ),
    ]
    funnel = me["funnel"]
    if funnel["found"]:
        top = funnel["found"]
        rows = [
            ("Найдено", funnel["found"] / top, str(funnel["found"])),
            ("Прислано", funnel["surfaced"] / top, str(funnel["surfaced"])),
            ("Открыл", funnel["opened"] / top, str(funnel["opened"])),
            ("Откликнулся", funnel["applied"] / top, str(funnel["applied"])),
        ]
        parts += ["<h4>🔻 Воронка недели</h4>", _chart(rows)]

    answers = [
        ("✅ отклик", "applied"),
        ("🚫 не прохожу", "mismatch"),
        ("👎 не интересно", "not_interested"),
        ("⛔ не пустил", "blocked"),
    ]
    total = sum(now.values())
    if total:
        rows = [(label, now[key] / total, f"{now[key]:>3}{_trend(now[key], before[key])}") for label, key in answers]
        parts += ["<h4>🗳 Твои ответы</h4>", _chart(rows)]

    platforms = [p for p in me["by_platform"] if p["decided"]]
    if platforms:
        rows = [
            (
                p["platform"],
                p["rate"] or 0.0,
                f"{_pct(p['rate']):>4} из {p['decided']}" + (f" ⛔{p['blocked']}" if p["blocked"] else ""),
            )
            for p in platforms
        ]
        parts += ["<h4>🏁 Площадки — доля откликов</h4>", _chart(rows)]

    tiers = me["by_tier_rate"]
    if any(rate is not None for rate in tiers.values()):
        rows = [(_TIERS[tier], rate, f"{rate:>4.0%}") for tier, rate in tiers.items() if rate is not None]
        parts += ["<h4>🎯 Откликаешься по тирам (🔥🔥🔥 / 🔥 / 👀) · 4 недели</h4>", _chart(rows)]

    if me["mismatch_reasons"]:
        reasons_total = sum(me["mismatch_reasons"].values())
        rows = [(MISMATCH_REASONS.get(k, k), v / reasons_total, f"{v:>3}") for k, v in me["mismatch_reasons"].items()]
        parts += ["<h4>🧩 Чего не хватает</h4>", _chart(rows)]
    if me["not_interested_reasons"]:
        line = " · ".join(f"{REJECT_REASONS.get(k, k)} {v}" for k, v in me["not_interested_reasons"].items())
        parts.append(f"<p>👎 Не интересно: {html.escape(line)}</p>")
    if me["applied_tech"]:
        line = " · ".join(f"{t['name']} {t['share']:.0%}" for t in me["applied_tech"])
        parts.append(f"<p>💼 Твой профиль по откликам: {html.escape(line)}</p>")
    if searches := me["searches"]:
        lines = [f"👍 {html.escape(s['label'])} — {s['rate']:.0%} из {s['n']}" for s in searches["best"]]
        lines += [f"👎 {html.escape(s['label'])} — {s['rate']:.0%} из {s['n']}" for s in searches["worst"]]
        parts.append("<h4>🔎 Поиски · 4 недели</h4><p>" + "<br>".join(lines) + "</p>")

    insights = [text for item in digest.get("my_insights") or [] if (text := _my_insight(item))]
    if insights:
        parts.append("<h4>💡 Выводы</h4><ul>" + "".join(f"<li>{text}</li>" for text in insights) + "</ul>")
    silent = digest.get("silent_sources") or []
    if silent:
        names = ", ".join(html.escape(name) for name in silent)
        parts.append(f"<p>⚠️ Ничего не дали за период: <b>{names}</b> — или блокируют, или сломалась вёрстка.</p>")
    parts.append(f"<footer>{total} решений за неделю · считаются по моменту нажатия кнопки</footer>")
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
