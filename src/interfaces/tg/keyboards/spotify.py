import hashlib

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.interfaces.tg.keyboards.grid import button_grid
from src.services.spotify.models import Member
from src.services.spotify.monobank import Account


class SpotifyCallback(CallbackData, prefix="spa"):
    """The owner's screens."""

    action: str
    member_id: int = 0
    arg: str = ""


class SpotifyMemberCallback(CallbackData, prefix="spm"):
    """A member's own screen."""

    action: str


def sender_key(name: str) -> str:
    """A sender name in 10 characters: callback data holds 64 bytes, a name may not fit."""
    return hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest()[:10]


def _button(
    text: str, action: str, member_id: int = 0, arg: str = "", style: str | None = None
) -> InlineKeyboardButton:
    data = SpotifyCallback(action=action, member_id=member_id, arg=arg).pack()
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def _back(action: str = "home", member_id: int = 0) -> InlineKeyboardButton:
    return _button("Вернуться 🔙", action, member_id)


def get_spotify_home_kb(members: list[Member], configured: bool) -> InlineKeyboardMarkup:
    if not configured:
        return InlineKeyboardMarkup(inline_keyboard=[[_button("⚙️ Настройка", "setup", style="primary")]])
    buttons = [
        _button(("👑 " if m.is_owner else "") + m.name + ("" if m.tg_id or m.is_owner else " ⚠️"), "member", m.id)
        for m in members
    ]
    rows = button_grid(buttons, columns=3)
    rows += [
        [_button("🔔 Напомнить должникам", "remind_all"), _button("📊 Статистика", "stats")],
        [_button("👥 Отправители", "senders"), _button("➕ Участник", "add")],
        [_button("⚙️ Настройка", "setup"), _button("Обновить 🔄", "sync")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_spotify_member_kb(member: Member) -> InlineKeyboardMarkup:
    notify = ("🔕 Без напоминаний", "notify_off") if member.notify else ("🔔 С напоминаниями", "notify_on")
    rows = [
        [
            _button("➕ Корректировка", "adjust", member.id, style="primary"),
            _button("🔔 Напомнить", "remind", member.id),
        ],
        [_button("🔗 Приглашение", "invite", member.id), _button(notify[0], notify[1], member.id)],
        [_button("✏️ Имя", "rename", member.id), _button("📅 Дата входа", "joined", member.id)],
        [],
    ]
    if not member.is_owner:
        leave = ("🚪 Вышел из подписки", "leave") if not member.left_on else ("↩️ Вернуть в подписку", "rejoin")
        rows[3].append(_button(leave[0], leave[1], member.id, style="danger" if not member.left_on else None))
    rows.append([_back()])
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def get_spotify_confirm_kb(action: str, member_id: int, text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button(text, action, member_id, style="danger"), _back("member", member_id)]]
    )


def get_spotify_cancel_kb(member_id: int = 0) -> InlineKeyboardMarkup:
    back = ("member", member_id) if member_id else ("home", 0)
    return InlineKeyboardMarkup(inline_keyboard=[[_button("✖️ Отмена", *back)]])


def get_spotify_back_kb(action: str = "home", member_id: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_back(action, member_id)]])


def get_spotify_senders_kb(senders: list[str]) -> InlineKeyboardMarkup:
    rows = [[_button(f"❓ {name}", "sender", arg=sender_key(name))] for name in senders[:20]]
    rows.append([_back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_spotify_sender_kb(name: str, members: list[Member], back: bool = True) -> InlineKeyboardMarkup:
    """Whose money is it: a member's second name, a new member, or not ours."""
    key = sender_key(name)
    buttons = [_button(f"→ {m.name}", "sender_to", m.id, key) for m in members if not m.left_on]
    rows = button_grid(buttons, columns=3)
    rows.append(
        [
            _button("➕ Новый участник", "sender_new", arg=key, style="success"),
            _button("🚫 Не учитывать", "sender_skip", arg=key),
        ]
    )
    if back:
        rows.append([_back("senders")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_spotify_setup_kb(accounts: list[Account], jar_id: str | None, card_id: str | None) -> InlineKeyboardMarkup:
    jars = [
        _button(("✅ " if a.id == jar_id else "") + f"🫙 {a.title}", "set_jar", arg=a.id) for a in accounts if a.is_jar
    ]
    cards = [
        _button(("✅ " if a.id == card_id else "") + f"💳 {a.title}", "set_card", arg=a.id)
        for a in accounts
        if not a.is_jar
    ]
    rows = button_grid(jars, columns=2) + button_grid(cards, columns=2)
    rows.append([_button("📥 Загрузить историю заново", "reload"), _button("🪝 Вебхук", "webhook")])
    rows.append([_back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_my_spotify_kb(member: Member, pay_url: str) -> InlineKeyboardMarkup:
    rows = []
    if pay_url:
        rows.append([InlineKeyboardButton(text="💳 Пополнить банку", url=pay_url, style="success")])
    notify = ("🔕 Выключить напоминания", "notify_off") if member.notify else ("🔔 Включить напоминания", "notify_on")
    rows.append(
        [
            InlineKeyboardButton(text=notify[0], callback_data=SpotifyMemberCallback(action=notify[1]).pack()),
            InlineKeyboardButton(text="Обновить 🔄", callback_data=SpotifyMemberCallback(action="me").pack()),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_pay_kb(pay_url: str) -> InlineKeyboardMarkup | None:
    if not pay_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Пополнить банку", url=pay_url)]])
