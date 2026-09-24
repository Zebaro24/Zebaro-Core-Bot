from datetime import UTC, datetime

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.interfaces.tg.formatters.vpn import status_emoji
from src.interfaces.tg.keyboards.grid import button_grid
from src.services.vpn.client import VpnClient


class VpnCallback(CallbackData, prefix="vpn"):
    action: str
    client_id: int = 0
    page: int = 0
    arg: str = ""


def _button(
    text: str, action: str, client_id: int = 0, page: int = 0, arg: str = "", style: str | None = None
) -> InlineKeyboardButton:
    data = VpnCallback(action=action, client_id=client_id, page=page, arg=arg).pack()
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def get_vpn_list_kb(clients: list[VpnClient], page: int = 0) -> InlineKeyboardMarkup:
    now = datetime.now(UTC)
    ordered = sorted(clients, key=lambda c: (not c.is_online(now), c.host_number or 999))
    buttons = [_button(f"{status_emoji(c, now)} {c.name} · {c.host_number}", "card", c.id) for c in ordered]
    rows = button_grid(buttons, page, lambda p: VpnCallback(action="list", page=p).pack())
    rows.append([_button("➕ Добавить", "add", style="success"), _button("Обновить 🔄", "list", page=page)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_vpn_card_kb(client: VpnClient) -> InlineKeyboardMarkup:
    toggle = ("⏸️ Выключить", "disable") if client.enabled else ("▶️ Включить", "enable")
    rows = [
        [_button("📄 Конфиги", "files", client.id, style="primary"), _button("💾 EXE для Windows", "exe", client.id)],
        [_button(toggle[0], toggle[1], client.id), _button("⏳ Срок доступа", "expiry_menu", client.id)],
        [_button("✏️ Имя", "rename", client.id), _button("🔢 IP", "readdress", client.id)],
        [_button("🗑️ Удалить", "delete", client.id, style="danger"), _button("Вернуться 🔙", "list")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_vpn_expiry_kb(client: VpnClient) -> InlineKeyboardMarkup:
    rows = [
        [
            _button("+1 день", "expiry", client.id, arg="1"),
            _button("+7 дней", "expiry", client.id, arg="7"),
            _button("+30 дней", "expiry", client.id, arg="30"),
        ],
        [_button("♾️ Бессрочно", "expiry", client.id, arg="none"), _button("Вернуться 🔙", "card", client.id)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_vpn_delete_kb(client: VpnClient) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("🗑️ Да, удалить", "delete_yes", client.id, style="danger"),
                _button("Отмена", "card", client.id),
            ]
        ]
    )


def get_vpn_cancel_kb(client_id: int = 0) -> InlineKeyboardMarkup:
    action = "card" if client_id else "list"
    return InlineKeyboardMarkup(inline_keyboard=[[_button("Отмена", action, client_id)]])


def get_vpn_expiring_kb(client: VpnClient) -> InlineKeyboardMarkup:
    """Under the "access ends tomorrow" notice: extend it without opening the card."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("+7 дней", "expiry", client.id, arg="7"),
                _button("+30 дней", "expiry", client.id, arg="30"),
                _button("Открыть", "card", client.id),
            ]
        ]
    )
