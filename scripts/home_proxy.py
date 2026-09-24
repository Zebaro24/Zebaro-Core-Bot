"""The job search's way into Work.ua, Robota.ua and HappyMonday — run it on the owner's PC.

Those boards refuse the server's datacenter IP and let a home IP through. The bot opens them
through this proxy over the VPN (src/services/job_searcher/home.py, HOME_PROXY_URL).

    python scripts/home_proxy.py            # reads HOME_PROXY_URL from ~/.zebaro/zebaro-core-bot-secrets.env

Standard library only: gost, the ready-made proxy, is removed by Windows Defender on sight
(an ML heuristic on Go binaries). What it allows, and nothing more:

* listens on the VPN address from HOME_PROXY_URL (10.0.0.2) — not on the home network;
* accepts only the server (10.0.0.1) and only with the login from HOME_PROXY_URL;
* only HTTPS tunnels (CONNECT to port 443) — the proxy never sees the pages themselves.

WireGuard on this PC must run the LAN profile: with the full one every connection leaves
through the server again, and the boards see the server's IP.
"""

import asyncio
import base64
import hmac
import logging
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

SECRETS = Path.home() / ".zebaro" / "zebaro-core-bot-secrets.env"
LOG_FILE = Path.home() / ".zebaro" / "home-proxy.log"
RETRY_S = 30
ALLOWED_PEERS = {"10.0.0.1"}
ALLOWED_PORTS = {443}
HEAD_LIMIT = 16 * 1024
CONNECT_TIMEOUT_S = 15

log = logging.getLogger("home-proxy")


def read_url(path: Path = SECRETS) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("HOME_PROXY_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"HOME_PROXY_URL не найден в {path}")


def expected_auth(url: str) -> str:
    parsed = urlparse(url)
    credentials = f"{unquote(parsed.username or '')}:{unquote(parsed.password or '')}"
    return "Basic " + base64.b64encode(credentials.encode()).decode()


async def _reply(writer: asyncio.StreamWriter, status: str, extra: str = "") -> None:
    writer.write(f"HTTP/1.1 {status}\r\n{extra}Content-Length: 0\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()
    writer.close()


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()


def make_handler(auth: str, allowed_peers: set[str] = ALLOWED_PEERS, allowed_ports: set[int] = ALLOWED_PORTS):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")[0]
        if peer not in allowed_peers:
            log.warning("refused %s: not the server", peer)
            writer.close()
            return
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=CONNECT_TIMEOUT_S)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            writer.close()
            return
        if len(head) > HEAD_LIMIT:
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        method, target, *_ = lines[0].split(" ") + ["", ""]
        headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:] if line)}

        # Chromium sends the login only after a 407 that asks for it.
        if not hmac.compare_digest(headers.get("proxy-authorization", ""), auth):
            await _reply(writer, "407 Proxy Authentication Required", 'Proxy-Authenticate: Basic realm="zebaro"\r\n')
            return
        host, _, port = target.rpartition(":")
        if method != "CONNECT" or not port.isdecimal() or int(port) not in allowed_ports:
            await _reply(writer, "405 Method Not Allowed")
            return
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(host.strip("[]"), int(port)), timeout=CONNECT_TIMEOUT_S
            )
        except (OSError, TimeoutError):
            await _reply(writer, "502 Bad Gateway")
            return
        log.info("tunnel %s:%s", host, port)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))

    return handle


async def serve(url: str) -> None:
    """Listen on the VPN address; while it is not there yet (WireGuard still starting after a
    logon, the laptop just woke up) keep trying instead of exiting."""
    parsed = urlparse(url)
    handler = make_handler(expected_auth(url))
    waiting_logged = False
    while True:
        try:
            server = await asyncio.start_server(handler, parsed.hostname, parsed.port)
        except OSError as e:
            if not waiting_logged:
                log.warning("%s:%s not available yet (%s) — WireGuard LAN on? retrying every %s s",
                            parsed.hostname, parsed.port, e, RETRY_S)  # fmt: skip
                waiting_logged = True
            await asyncio.sleep(RETRY_S)
            continue
        log.info("listening on %s:%s — only %s, only CONNECT :443", parsed.hostname, parsed.port, ", ".join(ALLOWED_PEERS))
        async with server:
            await server.serve_forever()


def _setup_logging() -> None:
    # pythonw (a startup shortcut, no window) has no console: the log goes to a file.
    target = {"stream": sys.stderr} if sys.stderr else {"filename": str(LOG_FILE), "encoding": "utf-8"}
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S", **target)


def main() -> None:
    _setup_logging()
    url = sys.argv[1] if len(sys.argv) > 1 else read_url()
    try:
        asyncio.run(serve(url))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
