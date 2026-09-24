"""VPN screens: the people on the WireGuard server, in the style of /server_status."""

from datetime import UTC, datetime
from html import escape

from src.services.vpn import addressing
from src.services.vpn.client import VpnClient
from src.services.vpn.traffic import Totals
from src.utils.format_memory import format_memory

_TABLE = "<table bordered striped compact>"


def status_emoji(client: VpnClient, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if client.expires_at and client.expires_at <= now:
        return "⌛"
    if not client.enabled:
        return "⏸️"
    return "🟢" if client.is_online(now) else "⚪"


def _ago(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "ещё не подключался"
    seconds = int((now - moment).total_seconds())
    if seconds < 180:
        return "сейчас"
    if seconds < 3600:
        return f"{seconds // 60} мин назад"
    if seconds < 86400:
        return f"{seconds // 3600} ч назад"
    return f"{seconds // 86400} дн назад"


def _bytes(value: int) -> str:
    if not value:
        return "—"
    if value < 1024**2:
        # format_memory starts at MB: a few handshakes' worth would read "0.00 MB".
        return f"{max(value // 1024, 1)} KB"
    return format_memory(value)


def _number(client: VpnClient) -> str:
    number = client.host_number
    return f".{number}" if number is not None else escape(client.ipv4)


def format_vpn_list(clients: list[VpnClient], week: dict[int, Totals], now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    online = sum(1 for c in clients if c.is_online(now))
    parts = [f"<h3>🔐 VPN · {len(clients)} устройств, онлайн {online}</h3>"]
    if not clients:
        parts.append("<p>Пока никого. «➕ Добавить» — и бот пришлёт готовые файлы.</p>")
        return "".join(parts)
    rows = "".join(
        f"<tr><td>{status_emoji(c, now)} {escape(c.name)}</td><td>{_number(c)}</td>"
        f'<td align="right">{_bytes(week.get(c.id, Totals()).tx)}</td>'
        f'<td align="right">{_bytes(week.get(c.id, Totals()).rx)}</td>'
        f"<td>{_ago(c.latest_handshake, now)}</td></tr>"
        for c in clients
    )
    parts.append(f"{_TABLE}<tr><th>Кто</th><th>IP</th><th>↓ 7 дн</th><th>↑ 7 дн</th><th>В сети</th></tr>{rows}</table>")
    total = sum((week.get(c.id, Totals()).total for c in clients), 0)
    parts.append(f"<p>Сеть <b>{addressing.NETWORK}</b> · трафик за неделю <b>{_bytes(total)}</b></p>")
    return "".join(parts)


def format_vpn_card(
    client: VpnClient, today: Totals, week: Totals, overall: Totals, now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    kind = addressing.kind(client.host_number)
    if client.expires_at:
        expiry = f"до {client.expires_at.astimezone():%d.%m.%Y %H:%M}"  # local time, like the rest
    else:
        expiry = "бессрочно"
    rows = [
        ("Статус", f"{status_emoji(client, now)} " + ("включён" if client.enabled else "выключен")),
        ("IP", f"<b>{escape(client.ipv4)}</b>" + (f" · {kind}" if kind else "")),
        ("В сети", _ago(client.latest_handshake, now)),
        ("Откуда", escape(client.endpoint.rpartition(":")[0]) if client.endpoint else "—"),
        ("Сегодня", f"↓ {_bytes(today.tx)} · ↑ {_bytes(today.rx)}"),
        ("7 дней", f"↓ {_bytes(week.tx)} · ↑ {_bytes(week.rx)}"),
        ("Всего", f"↓ {_bytes(overall.tx)} · ↑ {_bytes(overall.rx)}"),
        ("Доступ", expiry),
        ("Создан", f"{client.created_at:%d.%m.%Y}" if client.created_at else "—"),
    ]
    table = _TABLE + "".join(f"<tr><th>{label}</th><td>{value}</td></tr>" for label, value in rows) + "</table>"
    return f"<h3>🔐 {escape(client.name)}</h3>{table}"


def format_weekly_vpn(clients: list[VpnClient], week: dict[int, Totals]) -> str:
    """The Friday line-up: who used the VPN this week and how much."""
    used = sorted((c for c in clients if week.get(c.id, Totals()).total), key=lambda c: -week[c.id].total)
    parts = ["<h3>🔐 VPN за неделю</h3>"]
    if not used:
        parts.append("<p>Никто не подключался.</p>")
        return "".join(parts)
    rows = "".join(
        f"<tr><td>{escape(c.name)}</td><td>{_number(c)}</td>"
        f'<td align="right">{_bytes(week[c.id].tx)}</td><td align="right">{_bytes(week[c.id].rx)}</td></tr>'
        for c in used
    )
    parts.append(f"{_TABLE}<tr><th>Кто</th><th>IP</th><th>↓</th><th>↑</th></tr>{rows}</table>")
    total = sum(week[c.id].total for c in used)
    parts.append(f"<p>Всего <b>{_bytes(total)}</b> · не подключались: {len(clients) - len(used)}</p>")
    return "".join(parts)


def files_caption(client: VpnClient, full: str, lan: str) -> str:
    return (
        f"🔐 <b>{escape(client.name)}</b> · {escape(client.ipv4)}\n"
        f"<b>{escape(full)}</b> — весь интернет через VPN, реклама режется.\n"
        f"<b>{escape(lan)}</b> — только сеть VPN (сервер, общие папки).\n"
        "Один активен за раз: переключаются кнопкой в WireGuard."
    )


def exe_caption(client: VpnClient) -> str:
    return (
        f"💾 <b>Установщик для Windows</b> — {escape(client.name)}\n"
        "Сам поставит WireGuard (или оставит уже установленный), добавит оба профиля и включит "
        "VPN, если сейчас не включён другой. Windows может спросить «Запустить всё равно?» — "
        "файл без цифровой подписи."
    )
