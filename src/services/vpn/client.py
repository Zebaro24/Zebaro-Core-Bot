"""wg-easy's REST API (v15): the VPN server the bot manages.

wg-easy keeps the keys and the WireGuard interface; the bot only asks it for clients, their
traffic and their configuration. The container runs in the host network with its web UI bound
to the Docker bridge (172.17.0.1), so the API is reachable from the bot and not from outside.
Basic auth with the admin account wg-easy was initialised with (2FA must stay off for it).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger("vpn.client")

# A peer re-handshakes every two minutes while traffic flows; older than this it is idle.
ONLINE_WINDOW = timedelta(minutes=3)

PANEL_PORT = 51821

# wg-easy's own firewall hooks, owned by the bot (WgEasy.apply_hooks). Two things differ from
# wg-easy's defaults, both found on the server on 24.09.2026:
#
# * `iptables-nft`, not `iptables`: inside the image `iptables` is the legacy backend, while the
#   host and Docker (FORWARD policy DROP) live in nftables. The default rules landed in the
#   legacy tables, Docker's DROP in nft still applied, and the full profile had no internet.
#   The first two commands clean up those legacy rules, `|| true` because wg-quick runs hooks
#   under `set -e` and a missing rule must not take the interface down.
# * A DROP for the panel on wg0: the full profile routes everything into the server, and Linux
#   answers on any local address from any interface — a peer could open the panel on
#   172.17.0.1, where the admin account holds every peer's private key.
#
# {{ipv4Cidr}}, {{device}} and {{port}} are wg-easy's own placeholders.
_LEGACY_CLEANUP = (
    "iptables-legacy -t nat -D POSTROUTING -s {{ipv4Cidr}} -o {{device}} -j MASQUERADE 2>/dev/null || true; "
    "iptables-legacy -D FORWARD -i wg0 -j ACCEPT 2>/dev/null || true; "
    "iptables-legacy -D FORWARD -o wg0 -j ACCEPT 2>/dev/null || true; "
    "iptables-legacy -D INPUT -p udp -m udp --dport {{port}} -j ACCEPT 2>/dev/null || true;"
)
HOOK_POST_UP = (
    f"{_LEGACY_CLEANUP} "
    "iptables-nft -t nat -A POSTROUTING -s {{ipv4Cidr}} -o {{device}} -j MASQUERADE; "
    "iptables-nft -A INPUT -p udp -m udp --dport {{port}} -j ACCEPT; "
    "iptables-nft -I FORWARD -i wg0 -j ACCEPT; "
    "iptables-nft -I FORWARD -o wg0 -j ACCEPT; "
    f"iptables-nft -I INPUT -i wg0 -p tcp --dport {PANEL_PORT} -j DROP;"
)
HOOK_POST_DOWN = (
    "iptables-nft -t nat -D POSTROUTING -s {{ipv4Cidr}} -o {{device}} -j MASQUERADE || true; "
    "iptables-nft -D INPUT -p udp -m udp --dport {{port}} -j ACCEPT || true; "
    "iptables-nft -D FORWARD -i wg0 -j ACCEPT || true; "
    "iptables-nft -D FORWARD -o wg0 -j ACCEPT || true; "
    f"iptables-nft -D INPUT -i wg0 -p tcp --dport {PANEL_PORT} -j DROP || true;"
)


class VpnError(Exception):
    """wg-easy did not answer or refused the request."""


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class VpnClient:
    id: int
    name: str
    ipv4: str
    enabled: bool
    expires_at: datetime | None
    created_at: datetime | None
    latest_handshake: datetime | None
    endpoint: str | None
    rx: int  # bytes the server received from the client — its upload
    tx: int  # bytes the server sent to the client — its download
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "VpnClient":
        return cls(
            id=int(data["id"]),
            name=str(data.get("name") or ""),
            ipv4=str(data.get("ipv4Address") or ""),
            enabled=bool(data.get("enabled")),
            expires_at=_parse_time(data.get("expiresAt")),
            created_at=_parse_time(data.get("createdAt")),
            latest_handshake=_parse_time(data.get("latestHandshakeAt")),
            endpoint=data.get("endpoint"),
            rx=int(data.get("transferRx") or 0),
            tx=int(data.get("transferTx") or 0),
            raw=data,
        )

    @property
    def host_number(self) -> int | None:
        """The last octet: 10.0.0.18 → 18, the number the owner remembers a person by."""
        last = self.ipv4.rpartition(".")[2]
        return int(last) if last.isdigit() else None

    def is_online(self, now: datetime | None = None) -> bool:
        if not self.enabled or self.latest_handshake is None:
            return False
        return (now or datetime.now(UTC)) - self.latest_handshake <= ONLINE_WINDOW


# The fields POST /api/client/{id} accepts: it takes the whole client, so an update is
# read-modify-write over exactly these.
_UPDATE_FIELDS = (
    "name", "enabled", "expiresAt", "ipv4Address", "ipv6Address", "preUp", "postUp", "preDown",
    "postDown", "allowedIps", "serverAllowedIps", "firewallIps", "mtu", "jC", "jMin", "jMax", "i1",
    "i2", "i3", "i4", "i5", "persistentKeepalive", "serverEndpoint", "dns",
)  # fmt: skip


class WgEasy:
    def __init__(self, base_url: str | None = None, username: str | None = None, password: str | None = None):
        self.base_url = (base_url or settings.wg_easy_url).rstrip("/")
        self.auth = (username or settings.wg_easy_username, password or settings.wg_easy_password)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, auth=self.auth, timeout=10) as http:
                response = await http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise VpnError(f"wg-easy is unreachable: {e}") from e
        if response.status_code >= 400:
            raise VpnError(f"wg-easy answered {response.status_code} to {method} {path}")
        return response

    async def list_clients(self) -> list[VpnClient]:
        response = await self._request("GET", "/api/client")
        return [VpnClient.from_api(item) for item in response.json()]

    async def get_client(self, client_id: int) -> VpnClient:
        # From the list, not GET /api/client/{id}: only the list merges `wg dump` in — the
        # handshake and the transfer counters. The single client comes without them, and the
        # card would call everyone offline.
        for client in await self.list_clients():
            if client.id == client_id:
                return client
        raise VpnError(f"клиента {client_id} нет")

    async def apply_hooks(self) -> bool:
        """Put the bot's firewall hooks into wg-easy (see HOOK_POST_UP); True if they changed.

        Idempotent: nothing is sent while the hooks are already ours. When they change, the
        interface restarts once to run them — people in the VPN reconnect within seconds.
        """
        hooks = (await self._request("GET", "/api/admin/hooks")).json()
        if hooks.get("postUp") == HOOK_POST_UP and hooks.get("postDown") == HOOK_POST_DOWN:
            return False
        body = {
            "preUp": hooks.get("preUp") or "",
            "postUp": HOOK_POST_UP,
            "preDown": hooks.get("preDown") or "",
            "postDown": HOOK_POST_DOWN,
        }
        await self._request("POST", "/api/admin/hooks", json=body)
        await self._request("POST", "/api/admin/interface/restart")
        logger.info("wg-easy firewall hooks applied (nftables, panel closed to peers)")
        return True

    async def create_client(self, name: str, expires_at: datetime | None = None) -> int:
        body = {"name": name, "expiresAt": expires_at.isoformat() if expires_at else None}
        response = await self._request("POST", "/api/client", json=body)
        return int(response.json()["clientId"])

    async def update_client(self, client_id: int, **changes: Any) -> None:
        current = (await self._request("GET", f"/api/client/{client_id}")).json()
        body = {field: current.get(field) for field in _UPDATE_FIELDS}
        body.update(changes)
        await self._request("POST", f"/api/client/{client_id}", json=body)

    async def set_enabled(self, client_id: int, enabled: bool) -> None:
        await self._request("POST", f"/api/client/{client_id}/{'enable' if enabled else 'disable'}")

    async def delete_client(self, client_id: int) -> None:
        await self._request("DELETE", f"/api/client/{client_id}")

    async def configuration(self, client_id: int) -> str:
        response = await self._request("GET", f"/api/client/{client_id}/configuration")
        return response.text
