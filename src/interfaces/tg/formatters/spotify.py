"""Spotify family screens and notices: the owner's table, a member's card, reminders."""

from datetime import date, datetime
from html import escape

from src.services.spotify import ledger
from src.services.spotify.models import Adjustment, Charge, JarTransaction, Member
from src.services.spotify.report import Money, Snapshot, tz

_TABLE = "<table bordered striped compact>"
_MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
_MONTHS_UNTIL = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]  # fmt: skip


def uah(kopecks: int, sign: bool = False) -> str:
    text = f"{abs(kopecks) / 100:,.2f}".replace(",", " ")
    if kopecks < 0:
        return f"−{text} ₴"
    return f"+{text} ₴" if sign and kopecks > 0 else f"{text} ₴"


def usd(cents: int) -> str:
    return f"${cents / 100:.2f}"


def day(value: date) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]}"


def _moment(timestamp: int) -> str:
    return f"{datetime.fromtimestamp(timestamp, tz()):%d.%m.%Y}"


def paid_until(snap: Snapshot, member: Member) -> str:
    """ "оплачено до декабря" — the month of the first charge the balance no longer covers."""
    if not snap.upcoming:
        return ""
    share = snap.share(member)
    balance = snap.book[member.id].balance
    if member.is_owner:
        return "платит картой"
    if balance < 0:
        return "долг"
    months = ledger.months_covered(balance, share)
    upcoming = snap.upcoming.day
    index = upcoming.month - 1 + months
    month, year = _MONTHS_UNTIL[index % 12], upcoming.year + index // 12
    return f"оплачено до {month} {year}" if months else "на следующий месяц не хватает"


def _status(balance: int, share: int) -> str:
    if balance < 0:
        return "🔴"
    return "🟢" if balance >= share else "🟡"


def _linked(member: Member) -> str:
    if member.is_owner:
        return ""
    return "" if member.tg_id else " ⚠️"


def money_line(money: Money, amount: int) -> str:
    advice, value = money.advice(amount)
    if advice == "unknown":
        return "Баланс карты сейчас не узнать — Monobank не ответил."
    card = f"На чёрной карте <b>{uah(money.card or 0)}</b>"
    if advice == "ok":
        return f"✅ {card} — на списание хватает."
    if advice == "withdraw":
        return f"⚠️ {card} — не хватает {uah(value)}: <b>сними {uah(value)} из банки</b>."
    return f"⛔ {card}, в банке {uah(money.jar or 0)} — даже вместе не хватает <b>{uah(value)}</b>: нужно где-то взять."


# ── Owner ────────────────────────────────────────────────────────────────────


def format_overview(snap: Snapshot) -> str:
    parts = ["<h3>🎧 Spotify Family</h3>"]
    if not snap.configured:
        parts.append("<p>Банка и карта ещё не выбраны — «⚙️ Настройка».</p>")
        return "".join(parts)
    if not snap.members:
        parts.append("<p>Участников пока нет: «👥 Отправители» — бот предложит людей из банки.</p>")
    upcoming = snap.upcoming
    if upcoming:
        active = [m for m in snap.members if snap.share(m)]
        parts.append(
            f"<p>Следующее списание <b>{day(upcoming.day)}</b> ≈ <b>{uah(upcoming.amount)}</b> "
            f"({usd(upcoming.price)} × {upcoming.rate:.2f}) · по {uah(max(snap.shares.values(), default=0))} "
            f"на {len(active)}</p>"
        )
    rows = []
    for member in snap.members:
        account = snap.book[member.id]
        share = snap.share(member)
        left = f" (вышел {_moment_day(member.left_on)})" if member.left_on else ""
        if member.is_owner:  # the owner's share is paid by the card itself, not owed
            rows.append(
                f"<tr><td>👑 {escape(member.name)}</td><td align='right'>—</td>"
                f"<td align='right'>{uah(account.owed)}</td><td align='right'>—</td><td>платит картой</td></tr>"
            )
            continue
        rows.append(
            f"<tr><td>{_status(account.balance, share)} {escape(member.name)}{_linked(member)}{left}</td>"
            f'<td align="right">{uah(account.paid)}</td><td align="right">{uah(account.owed)}</td>'
            f'<td align="right"><b>{uah(account.balance, sign=True)}</b></td>'
            f"<td>{paid_until(snap, member) if not member.left_on else ''}</td></tr>"
        )
    if rows:
        parts.append(
            f"{_TABLE}<tr><th>Кто</th><th>Внёс</th><th>Доля</th><th>Баланс</th><th></th></tr>{''.join(rows)}</table>"
        )
    unlinked = [m.name for m in snap.members if not m.is_owner and not m.tg_id and not m.left_on]
    if unlinked:
        parts.append(
            f"<p>⚠️ Не подключены к боту: {escape(', '.join(unlinked))} — им не придут напоминания. "
            "Открой человека → «🔗 Приглашение» и перешли ссылку.</p>"
        )
    if upcoming and snap.money.card is not None:
        jar = f"В банке <b>{uah(snap.money.jar or 0)}</b>. " if snap.money.jar is not None else ""
        parts.append(f"<p>{jar}{money_line(snap.money, upcoming.amount)}</p>")
    return "".join(parts)


def _moment_day(value: date | None) -> str:
    return f"{value:%d.%m.%Y}" if value else ""


def format_stats(snap: Snapshot) -> str:
    charges = [c for c in snap.charges if c.amount > 0]
    parts = ["<h3>📊 Spotify · статистика</h3>"]
    if not charges:
        parts.append("<p>Списаний ещё нет.</p>")
        return "".join(parts)
    first, last = charges[0], charges[-1]
    total = sum(c.amount for c in snap.charges)
    parts.append(
        f"<p>С {_moment(first.time)}: <b>{len(charges)}</b> списаний на <b>{uah(total)}</b>, "
        f"в среднем {uah(total // len(charges))}.</p>"
    )
    by_year: dict[int, list[Charge]] = {}
    for charge in snap.charges:
        by_year.setdefault(datetime.fromtimestamp(charge.time, tz()).year, []).append(charge)
    rows = "".join(
        f"<tr><td>{year}</td><td align='right'>{sum(1 for c in items if c.amount > 0)}</td>"
        f"<td align='right'>{uah(sum(c.amount for c in items))}</td>"
        f"<td align='right'>{uah(max(c.amount for c in items))}</td></tr>"
        for year, items in sorted(by_year.items())
    )
    parts.append(f"{_TABLE}<tr><th>Год</th><th>Списаний</th><th>Сумма</th><th>Самое дорогое</th></tr>{rows}</table>")
    growth = (last.amount - first.amount) / first.amount * 100 if first.amount else 0
    parts.append(
        f"<p>Цена: {uah(first.amount)} ({usd(first.operation_amount)}) → {uah(last.amount)} "
        f"({usd(last.operation_amount)}), {growth:+.0f}% — в основном курс.</p>"
    )
    if snap.book.unshared:
        parts.append(f"<p>⚠️ {uah(snap.book.unshared)} списаний пришлись на дни, когда участников не было.</p>")
    return "".join(parts)


def _history_rows(
    member: Member, snap: Snapshot, transactions: list[JarTransaction], adjustments: list[Adjustment], limit: int
) -> list[tuple[int, str, int]]:
    """(time, what, ± kopecks) of a member, newest first."""
    events: list[tuple[int, str, int]] = []
    for t in transactions:
        if ledger.counted(t):
            note = f" · «{escape(t.comment)}»" if t.comment else ""
            events.append((t.time, f"💳 в банку{note}", t.amount))
    for a in adjustments:
        events.append((a.time, f"📝 {escape(a.note) or 'корректировка'}", a.amount))
    for charge in snap.charges:
        on = ledger.local_day(charge.time, tz())
        if member.active_on(on):
            share = ledger.split(charge.amount, [m for m in snap.members if m.active_on(on)]).get(member.id, 0)
            events.append((charge.time, "🎧 доля списания", -share))
    events.sort(key=lambda e: e[0], reverse=True)
    return events[:limit]


def format_member_card(
    snap: Snapshot, member: Member, transactions: list[JarTransaction], adjustments: list[Adjustment]
) -> str:
    account = snap.book[member.id]
    share = snap.share(member)
    link = "🔗 подключён к боту" if member.tg_id else "⚠️ не подключён к боту"
    if member.is_owner:
        link = "👑 владелец"
    names = ", ".join(escape(a.name) for a in member.aliases) or "—"
    by_hand = f", {uah(account.adjustments, sign=True)} 📝" if account.adjustments else ""
    until = f" по {_moment_day(member.left_on)}" if member.left_on else ""
    rows = [
        ("Баланс", f"<b>{uah(account.balance, sign=True)}</b> · {paid_until(snap, member)}"),
        ("Внёс", f"{uah(account.topups)} в банку{by_hand}"),
        ("Доля", f"{uah(account.owed)} за {account.charges} списаний"),
        ("Следующая", uah(share) if share else "—"),
        ("В Monobank", names),
        ("В подписке", f"с {_moment_day(member.joined_on)}{until}"),
        ("Бот", link + ("" if member.notify else " · напоминания выкл")),
    ]
    table = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
    parts = [f"<h3>🎧 {escape(member.name)}</h3>{_TABLE}{table}</table>"]
    history = _history_rows(member, snap, transactions, adjustments, 12)
    if history:
        lines = "".join(
            f"<tr><td>{_moment(at)}</td><td>{what}</td><td align='right'>{uah(amount, sign=True)}</td></tr>"
            for at, what, amount in history
        )
        parts.append(f"<p>Последние операции:</p>{_TABLE}{lines}</table>")
    return "".join(parts)


def format_senders(senders: list[tuple[str, int, int]]) -> str:
    parts = ["<h3>👥 Новые отправители в банке</h3>"]
    if not senders:
        parts.append("<p>Все, кто пополнял банку, уже разобраны.</p>")
        return "".join(parts)
    rows = "".join(
        f"<tr><td>{escape(name)}</td><td align='right'>{count}</td><td align='right'>{uah(total)}</td></tr>"
        for name, count, total in senders
    )
    parts.append(f"{_TABLE}<tr><th>Имя в Monobank</th><th>Раз</th><th>Всего</th></tr>{rows}</table>")
    parts.append("<p>Нажми на имя: новый участник, чей-то второй аккаунт или «не учитывать».</p>")
    return "".join(parts)


# ── Member ───────────────────────────────────────────────────────────────────


def format_my_card(
    snap: Snapshot, member: Member, transactions: list[JarTransaction], adjustments: list[Adjustment]
) -> str:
    account = snap.book[member.id]
    share = snap.share(member)
    parts = [f"<h3>🎧 Spotify Family · {escape(member.name)}</h3>"]
    balance = uah(account.balance, sign=True)
    parts.append(f"<p>Баланс <b>{balance}</b> — {paid_until(snap, member)}.</p>")
    if snap.upcoming and share:
        pay = ledger.to_pay(account.balance, share)
        need = f"закинуть <b>{uah(pay)}</b>" if pay else "ничего докидывать не нужно ✅"
        parts.append(f"<p>Следующее списание {day(snap.upcoming.day)}, твоя доля ≈ {uah(share)} — {need}.</p>")
    history = _history_rows(member, snap, transactions, adjustments, 12)
    if history:
        lines = "".join(
            f"<tr><td>{_moment(at)}</td><td>{what}</td><td align='right'>{uah(amount, sign=True)}</td></tr>"
            for at, what, amount in history
        )
        parts.append(f"{_TABLE}{lines}</table>")
    return "".join(parts)


# ── Notices (plain HTML messages) ────────────────────────────────────────────


def notice_topup(snap: Snapshot, member: Member, amount: int) -> str:
    balance = snap.book[member.id].balance
    return (
        f"✅ Получил <b>{uah(amount)}</b> в банку Spotify. "
        f"Баланс {uah(balance, sign=True)} — {paid_until(snap, member)}."
    )


def notice_status(snap: Snapshot, member: Member) -> str:
    balance = snap.book[member.id].balance
    return f"🎧 Spotify Family: баланс {uah(balance, sign=True)} — {paid_until(snap, member)}."


def notice_topup_owner(member: Member, transaction: JarTransaction, snap: Snapshot) -> str:
    comment = f" · «{escape(transaction.comment)}»" if transaction.comment else ""
    balance = snap.book[member.id].balance
    return (
        f"🎧 {escape(member.name)} → банка <b>{uah(transaction.amount)}</b>{comment} · баланс {uah(balance, sign=True)}"
    )


def notice_unknown(transaction: JarTransaction) -> str:
    comment = f" · «{escape(transaction.comment)}»" if transaction.comment else ""
    return (
        f"🎧 В банку пришло <b>{uah(transaction.amount)}</b> от <b>{escape(transaction.sender or '?')}</b>{comment}.\n"
        "Этого имени бот не знает — чьи это деньги?"
    )


def notice_before(snap: Snapshot, member: Member) -> str:
    account = snap.book[member.id]
    share = snap.share(member)
    pay = ledger.to_pay(account.balance, share)
    assert snap.upcoming
    return (
        f"🎧 {day(snap.upcoming.day)} списание Spotify Family, твоя доля ≈ <b>{uah(share)}</b>.\n"
        f"Баланс {uah(account.balance, sign=True)} → закинь в банку <b>{uah(pay)}</b>."
    )


def notice_debt(snap: Snapshot, member: Member, charge: Charge | None) -> str:
    account = snap.book[member.id]
    head = f"🎧 Spotify списал {uah(charge.amount)}" if charge else "🎧 Spotify Family"
    share = ""
    if charge:
        on = ledger.local_day(charge.time, tz())
        part = ledger.split(charge.amount, [m for m in snap.members if m.active_on(on)]).get(member.id, 0)
        share = f", твоя доля {uah(part)}"
    return f"{head}{share}.\nУ тебя долг <b>{uah(-account.balance)}</b> — закинь в банку, пожалуйста."


def notice_owner_before(snap: Snapshot, short: list[Member]) -> str:
    assert snap.upcoming
    upcoming = snap.upcoming
    lines = [f"🎧 <b>{day(upcoming.day)}</b> списание Spotify ≈ <b>{uah(upcoming.amount)}</b> ({usd(upcoming.price)})."]
    if snap.money.jar is not None:
        lines.append(f"В банке {uah(snap.money.jar)}.")
    lines.append(money_line(snap.money, upcoming.amount))
    if short:
        owes = ", ".join(
            f"{escape(m.name)} {uah(ledger.to_pay(snap.book[m.id].balance, snap.share(m)))}" for m in short
        )
        lines.append(f"Ещё не докинули: {owes}.")
    else:
        lines.append("Все участники уже оплатили ✅")
    return "\n".join(lines)


def notice_owner_charge(snap: Snapshot, charge: Charge, price_changed: int | None) -> str:
    lines = [f"🎧 Spotify списал <b>{uah(charge.amount)}</b> ({usd(charge.operation_amount)})."]
    if price_changed is not None:
        lines.append(f"⚠️ Цена в долларах изменилась: {usd(price_changed)} → {usd(charge.operation_amount)}.")
    debtors = [m for m in snap.members if not m.is_owner and snap.book[m.id].balance < 0 and not m.left_on]
    if debtors:
        lines.append("Должны: " + ", ".join(f"{escape(m.name)} {uah(-snap.book[m.id].balance)}" for m in debtors))
    else:
        lines.append("Долгов нет ✅")
    if snap.upcoming:
        lines.append(f"Следующее ≈ {uah(snap.upcoming.amount)} {day(snap.upcoming.day)}.")
    return "\n".join(lines)


def notice_leave(snap: Snapshot, member: Member) -> str:
    balance = snap.book[member.id].balance
    if balance > 0:
        settle = f"переплата {uah(balance)} — вернуть деньгами или закрыть корректировкой"
    elif balance < 0:
        settle = f"долг {uah(-balance)}"
    else:
        settle = "в расчёте ноль"
    return f"👋 {escape(member.name)} выходит из подписки. Итог: {settle}."
