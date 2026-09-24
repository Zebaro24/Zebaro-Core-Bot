"""scripts/home_proxy.py — the proxy the owner runs on his PC for the job search."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("home_proxy", Path(__file__).parent.parent / "scripts" / "home_proxy.py")
assert _SPEC and _SPEC.loader
home_proxy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(home_proxy)

URL = "http://zebaro:s3cret@127.0.0.1:0"
AUTH = home_proxy.expected_auth(URL)


async def _echo_server():
    async def echo(reader, writer):
        writer.write(await reader.read(100))
        await writer.drain()
        writer.close()

    return await asyncio.start_server(echo, "127.0.0.1", 0)


async def _proxy(peers=frozenset({"127.0.0.1"}), ports=frozenset()):
    return await asyncio.start_server(home_proxy.make_handler(AUTH, set(peers), set(ports)), "127.0.0.1", 0)


async def _ask(proxy, request: bytes) -> bytes:
    port = proxy.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(request)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(200), 5)
    except ConnectionResetError:
        return b""  # dropped: Windows reports the closed socket as a reset
    writer.close()
    return data


def test_auth_header_from_the_url():
    assert AUTH == "Basic emViYXJvOnMzY3JldA=="
    assert home_proxy.expected_auth("http://a%40b:p%3Aw@10.0.0.2:8899") == "Basic YUBiOnA6dw=="


@pytest.mark.asyncio
async def test_without_the_login_it_asks_for_it():
    proxy = await _proxy()
    async with proxy:
        answer = await _ask(proxy, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 407") and b'Proxy-Authenticate: Basic realm="zebaro"' in answer


@pytest.mark.asyncio
async def test_only_https_tunnels():
    proxy = await _proxy()
    async with proxy:
        plain = await _ask(proxy, f"GET http://example.com/ HTTP/1.1\r\nProxy-Authorization: {AUTH}\r\n\r\n".encode())
        other_port = await _ask(
            proxy, f"CONNECT example.com:22 HTTP/1.1\r\nProxy-Authorization: {AUTH}\r\n\r\n".encode()
        )
    assert plain.startswith(b"HTTP/1.1 405") and other_port.startswith(b"HTTP/1.1 405")


@pytest.mark.asyncio
async def test_anyone_but_the_server_is_dropped():
    proxy = await _proxy(peers={"10.0.0.1"})
    async with proxy:
        answer = await _ask(proxy, f"CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: {AUTH}\r\n\r\n".encode())
    assert answer == b""


@pytest.mark.asyncio
async def test_a_tunnel_carries_bytes_both_ways():
    echo = await _echo_server()
    echo_port = echo.sockets[0].getsockname()[1]
    proxy = await _proxy(ports={echo_port})
    async with echo, proxy:
        port = proxy.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"CONNECT 127.0.0.1:{echo_port} HTTP/1.1\r\nProxy-Authorization: {AUTH}\r\n\r\n".encode())
        await writer.drain()
        assert (await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)).startswith(b"HTTP/1.1 200")
        writer.write(b"ping")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(10), 5) == b"ping"
        writer.close()
