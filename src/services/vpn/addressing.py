"""Addresses in the VPN, chosen to be remembered: 10.0.0.<number>.

.1         the server itself (Samba at \\\\10.0.0.1, the wg-easy panel)
.2 – .9    the owner's own devices (.2 is the home PC the job search goes through)
.10 – .99  people the owner gives a number of his choosing
.100 – .254  handed out automatically when no number is given
"""

from ipaddress import IPv4Address, IPv4Network

NETWORK = IPv4Network("10.0.0.0/24")
SERVER = 1
OWNER = range(2, 10)
CHOSEN = range(10, 100)
AUTO = range(100, 255)


class AddressError(ValueError):
    """The number cannot be given: out of range or taken."""


def address(number: int) -> str:
    return str(NETWORK.network_address + number)


def number_of(ip: str) -> int | None:
    try:
        value = IPv4Address(ip)
    except ValueError:
        return None
    return int(value) - int(NETWORK.network_address) if value in NETWORK else None


def pick(taken: set[int], wanted: int | None = None) -> int:
    """The number for a new or moved client: the wanted one if free, else the first free auto one."""
    if wanted is not None:
        if wanted == SERVER or not 2 <= wanted <= 254:
            raise AddressError(f"{wanted}: номер должен быть от 2 до 254 (1 — сам сервер)")
        if wanted in taken:
            raise AddressError(f"{address(wanted)} уже занят")
        return wanted
    for number in AUTO:
        if number not in taken:
            return number
    raise AddressError("в автоматическом диапазоне .100–.254 не осталось адресов")


def kind(number: int | None) -> str:
    if number is None:
        return ""
    if number == SERVER:
        return "сервер"
    if number in OWNER:
        return "твоё устройство"
    if number in CHOSEN:
        return "свой номер"
    return "авто"
