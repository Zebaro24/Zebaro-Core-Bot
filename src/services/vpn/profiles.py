"""The two profiles every person gets, from one key.

* ``Zebaro-<Name>``      — everything through the VPN (ads cut by AdGuard DNS)
* ``Zebaro-<Name>-LAN``  — only the VPN network: the server (Samba), the other devices

Both use the same key, so only one can be active at a time — switching is one click in the
WireGuard client. The tunnel name is the file name, and WireGuard for Windows allows only
[A-Za-z0-9_=+.-] up to 32 characters, hence the transliteration. The "Zebaro-" prefix keeps
our tunnels apart from any VPN the person already has.
"""

import re
from dataclasses import dataclass

from src.services.vpn.addressing import NETWORK

PREFIX = "Zebaro"
_TUNNEL_MAX = 32
_LAN_SUFFIX = "-LAN"

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ye", "ё": "yo",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh",
    "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}  # fmt: skip


def slug(name: str) -> str:
    """ "Олена Ковальчук" → "Olena-Kovalchuk": safe for a tunnel and a file name."""
    out = []
    for char in name.strip():
        lower = char.lower()
        if lower in _TRANSLIT:
            latin = _TRANSLIT[lower]
            out.append(latin.capitalize() if char != lower and latin else latin)
        else:
            out.append(char)
    text = re.sub(r"[^A-Za-z0-9_=+.-]+", "-", "".join(out)).strip("-.")
    return re.sub(r"-{2,}", "-", text) or "User"


def tunnel_name(name: str, lan: bool = False) -> str:
    suffix = _LAN_SUFFIX if lan else ""
    room = _TUNNEL_MAX - len(PREFIX) - 1 - len(suffix)
    return f"{PREFIX}-{slug(name)[:room].rstrip('-.')}{suffix}"


@dataclass
class Profile:
    tunnel: str
    config: str

    @property
    def filename(self) -> str:
        return f"{self.tunnel}.conf"


def _with_allowed_ips(config: str, allowed: str) -> str:
    lines = [
        f"AllowedIPs = {allowed}" if line.strip().lower().startswith("allowedips") else line
        for line in config.splitlines()
    ]
    return "\n".join(lines) + "\n"


def profiles(name: str, config: str) -> tuple[Profile, Profile]:
    """The full and the LAN profile from the configuration wg-easy generated."""
    full = Profile(tunnel_name(name), config if config.endswith("\n") else config + "\n")
    lan = Profile(tunnel_name(name, lan=True), _with_allowed_ips(config, str(NETWORK)))
    return full, lan
