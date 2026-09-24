import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock()

from src.interfaces.tg.formatters.vpn import format_vpn_card, format_vpn_list, status_emoji  # noqa: E402
from src.interfaces.tg.handlers.admin.vpn import parse_new  # noqa: E402
from src.services.vpn import addressing, installer, traffic  # noqa: E402
from src.services.vpn.client import VpnClient, WgEasy  # noqa: E402
from src.services.vpn.profiles import profiles, slug, tunnel_name  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
CONFIG = """[Interface]
PrivateKey = key
Address = 10.0.0.18/24
DNS = 94.140.14.14, 94.140.15.15

[Peer]
PublicKey = pub
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = server.zebaro.dev:51820
"""


def _client(**overrides) -> VpnClient:
    data = {
        "id": 3,
        "name": "Олена",
        "ipv4Address": "10.0.0.18",
        "enabled": True,
        "expiresAt": None,
        "createdAt": "2026-09-20T10:00:00.000Z",
        "latestHandshakeAt": (NOW - timedelta(seconds=40)).isoformat(),
        "endpoint": "93.170.1.2:51000",
        "transferRx": 1000,
        "transferTx": 5000,
    }
    data.update(overrides)
    return VpnClient.from_api(data)


# --- addresses -------------------------------------------------------------------------


def test_a_chosen_number_is_given_when_free():
    assert addressing.pick({1, 100}, 18) == 18
    assert addressing.address(18) == "10.0.0.18"


def test_without_a_number_the_first_free_auto_address():
    assert addressing.pick({1, 2, 100, 101}) == 102


@pytest.mark.parametrize("wanted", [1, 0, 255, 18])
def test_a_number_that_cannot_be_given(wanted):
    with pytest.raises(addressing.AddressError):
        addressing.pick({1, 18}, wanted)


def test_kinds():
    assert addressing.kind(2) == "твоё устройство"
    assert addressing.kind(18) == "свой номер"
    assert addressing.kind(140) == "авто"
    assert addressing.number_of("10.0.0.18") == 18
    assert addressing.number_of("192.168.1.5") is None


@pytest.mark.parametrize(
    "text,expected",
    [("Олена 18", ("Олена", 18)), ("Олена Ковальчук", ("Олена Ковальчук", None)), ("Ноут .5", ("Ноут", 5))],
)
def test_parse_new(text, expected):
    assert parse_new(text) == expected


# --- profiles --------------------------------------------------------------------------


def test_names_become_safe_tunnel_names():
    assert slug("Олена Ковальчук") == "Olena-Kovalchuk"
    assert slug("Їжак & Co") == "Yizhak-Co"
    assert slug("!!!") == "User"
    long = tunnel_name("Максиміліан Олександрович Костянтинопольський", lan=True)
    assert long.startswith("Zebaro-Maksymilian") and long.endswith("-LAN") and len(long) <= 32


def test_the_lan_profile_only_routes_the_vpn_network():
    full, lan = profiles("Олена", CONFIG)
    assert full.filename == "Zebaro-Olena.conf" and lan.filename == "Zebaro-Olena-LAN.conf"
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in full.config
    assert "AllowedIPs = 10.0.0.0/24" in lan.config and "0.0.0.0/0" not in lan.config
    assert "PrivateKey = key" in lan.config  # one key, two profiles


def test_installer_bat_line_ends_and_missing_parts(mocker):
    assert installer._crlf("a\nb\r\nc") == b"a\r\nb\r\nc"
    mocker.patch.object(
        installer, "_assets", return_value=MagicMock(__truediv__=lambda s, n: MagicMock(is_file=lambda: False))
    )
    with pytest.raises(installer.InstallerUnavailable):
        installer.build_exe(*profiles("Олена", CONFIG))


# --- the wg-easy client ----------------------------------------------------------------


def test_client_state_from_the_api():
    client = _client()
    assert client.host_number == 18
    assert client.is_online(NOW)
    assert not _client(latestHandshakeAt=(NOW - timedelta(minutes=10)).isoformat()).is_online(NOW)
    assert not _client(enabled=False).is_online(NOW)


@pytest.mark.asyncio
async def test_an_update_sends_the_whole_client_back_with_the_change(mocker):
    current = {"name": "Олена", "enabled": True, "ipv4Address": "10.0.0.18", "ipv6Address": "fd::2", "extra": 1}
    request = AsyncMock(side_effect=[MagicMock(json=MagicMock(return_value=current)), MagicMock()])
    wg = WgEasy("http://wg", "u", "p")
    mocker.patch.object(wg, "_request", request)

    await wg.update_client(3, ipv4Address="10.0.0.20")

    method, path = request.await_args_list[1].args
    body = request.await_args_list[1].kwargs["json"]
    assert (method, path) == ("POST", "/api/client/3")
    assert body["ipv4Address"] == "10.0.0.20" and body["ipv6Address"] == "fd::2" and body["name"] == "Олена"
    assert "extra" not in body  # only the fields wg-easy's update schema takes


# --- traffic ---------------------------------------------------------------------------


def test_a_counter_restart_counts_from_zero_not_negative():
    assert traffic.delta(None, 500) == 500
    assert traffic.delta(300, 500) == 200
    assert traffic.delta(900, 120) == 120  # the interface restarted


@pytest.mark.asyncio
async def test_snapshot_keeps_totals_and_reports_first_connection_and_expiry(mocker):
    clients_col = MagicMock(find_one=AsyncMock(return_value={"last_rx": 400, "last_tx": 1000, "total_rx": 4000}))
    clients_col.update_one = AsyncMock()
    daily_col = MagicMock(update_one=AsyncMock())
    mocker.patch.object(traffic, "vpn_clients_collection", clients_col)
    mocker.patch.object(traffic, "vpn_daily_collection", daily_col)
    client = _client(expiresAt=(NOW + timedelta(hours=5)).isoformat())

    events = await traffic.snapshot([client], now=NOW)

    stored = clients_col.update_one.await_args.args[1]["$set"]
    assert stored["total_rx"] == 4600 and stored["total_tx"] == 4000
    assert events.first_connected == [client] and events.expiring == [client]
    assert daily_col.update_one.await_args.args[1]["$inc"] == {"rx": 600, "tx": 4000}

    # Next snapshot: the same expiry is not announced twice.
    clients_col.find_one = AsyncMock(return_value={**stored, "first_connected_at": NOW})
    again = await traffic.snapshot([client], now=NOW)
    assert again.first_connected == [] and again.expiring == []


# --- screens ---------------------------------------------------------------------------


def test_status_emoji():
    assert status_emoji(_client(), NOW) == "🟢"
    assert status_emoji(_client(enabled=False), NOW) == "⏸️"
    assert status_emoji(_client(expiresAt=(NOW - timedelta(days=1)).isoformat()), NOW) == "⌛"
    assert status_emoji(_client(latestHandshakeAt=None), NOW) == "⚪"


def test_list_and_card_screens():
    client = _client(name="<Олена>")
    week = {3: traffic.Totals(rx=2 * 1024**2, tx=10 * 1024**2)}
    html = format_vpn_list([client], week, NOW)
    assert "1 устройств, онлайн 1" in html
    assert "&lt;Олена&gt;" in html and "<td>.18</td>" in html

    card = format_vpn_card(client, traffic.Totals(), week[3], week[3], NOW)
    assert "10.0.0.18</b> · свой номер" in card
    assert "93.170.1.2" in card and "51000" not in card
    assert "бессрочно" in card


# --- review fixes ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_single_client_comes_from_the_list_with_its_handshake(mocker):
    wg = WgEasy("http://wg", "u", "p")
    listed = _client()
    mocker.patch.object(wg, "list_clients", AsyncMock(return_value=[_client(id=1), listed]))

    assert (await wg.get_client(3)).latest_handshake == listed.latest_handshake


@pytest.mark.asyncio
async def test_the_panel_is_closed_to_peers_once(mocker):
    from src.services.vpn.client import PANEL_DROP_DOWN, PANEL_DROP_UP

    wg = WgEasy("http://wg", "u", "p")
    hooks = {"preUp": "", "postUp": "iptables -t nat -A POSTROUTING;", "preDown": "", "postDown": "x;"}
    request = AsyncMock(side_effect=[MagicMock(json=MagicMock(return_value=hooks)), MagicMock(), MagicMock()])
    mocker.patch.object(wg, "_request", request)

    assert await wg.close_panel_to_peers() is True
    body = request.await_args_list[1].kwargs["json"]
    assert body["postUp"].startswith(PANEL_DROP_UP) and "POSTROUTING" in body["postUp"]
    assert body["postDown"].startswith(PANEL_DROP_DOWN)
    assert request.await_args_list[2].args == ("POST", "/api/admin/interface/restart")

    closed = {**hooks, "postUp": body["postUp"]}
    request = AsyncMock(return_value=MagicMock(json=MagicMock(return_value=closed)))
    mocker.patch.object(wg, "_request", request)
    assert await wg.close_panel_to_peers() is False
    assert request.await_count == 1  # no restart when nothing changed


@pytest.mark.asyncio
async def test_no_first_connection_notice_for_someone_connected_before_the_bot_watched(mocker):
    clients_col = MagicMock(find_one=AsyncMock(return_value=None), update_one=AsyncMock())
    mocker.patch.object(traffic, "vpn_clients_collection", clients_col)
    mocker.patch.object(traffic, "vpn_daily_collection", MagicMock(update_one=AsyncMock()))
    old = _client(createdAt=(NOW - timedelta(days=30)).isoformat())

    events = await traffic.snapshot([old], now=NOW)

    assert events.first_connected == []


@pytest.mark.asyncio
async def test_history_is_empty_not_fatal_when_mongo_is_down(mocker):
    broken = MagicMock(find=MagicMock(side_effect=Exception("no db")))
    mocker.patch.object(traffic, "vpn_clients_collection", broken)
    mocker.patch.object(traffic, "vpn_daily_collection", broken)

    assert (await traffic.totals([3]))[3].total == 0
    assert (await traffic.period([3], days=7))[3].total == 0


def test_a_command_typed_into_a_form_is_not_taken_as_a_name():
    from src.interfaces.tg.handlers.admin.vpn import _FORM_TEXT

    assert _FORM_TEXT.resolve(MagicMock(text="Олена 18"))
    assert not _FORM_TEXT.resolve(MagicMock(text="/services"))


@pytest.mark.asyncio
async def test_extending_access_keeps_a_paused_client_paused_but_revives_an_expired_one(mocker):
    from src.interfaces.tg.handlers.admin import vpn as handler

    wg = MagicMock(update_client=AsyncMock())
    wg.get_client = AsyncMock(return_value=_client(enabled=False))
    await handler._set_expiry(wg, 3, "7")
    assert wg.update_client.await_args.kwargs["enabled"] is False

    wg.get_client = AsyncMock(return_value=_client(enabled=False, expiresAt="2020-01-01T00:00:00Z"))
    await handler._set_expiry(wg, 3, "7")
    assert wg.update_client.await_args.kwargs["enabled"] is True
