"""The cage's one way out: a proxy that runs as you and forwards only to pinned hosts.

Project 4b of docs/superpowers/plans/2026-09-22-caged-server.md. The firewall rule
(scripts/cage/enable_network_fence.ps1) stops the cage account reaching any
address but loopback. What it may still reach -- the model providers, PyPI, npm --
it reaches through this proxy, which runs inside the promoter service as you,
listens only on loopback, and opens a tunnel (HTTP CONNECT, port 443 only) only to
a host listed in egress.allow, a pin in C:\\ProgramData\\ThomasPins that only an
administrator can change. A missing or unreadable pin allows nothing.

It forwards bytes and reads none of them: the tunnel is TLS end to end between the
cage and the host. What it decides is where a connection may go, and it re-reads
the pin for every connection, so a change an administrator makes applies at once.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from pathlib import Path

PORT = 8897
PIN_NAME = "egress.allow"
DEFAULT_PIN_ROOT = Path(r"C:\ProgramData\ThomasPins")
ALLOWED_PORTS = frozenset({443})
_MAX_HEAD = 8192
_HEAD_TIMEOUT_S = 10.0
_CONNECT_TIMEOUT_S = 15.0

log = logging.getLogger("thomas.egress_proxy")


def load_allowlist(pin_root: Path | None = None) -> frozenset[str]:
    """Hosts from the pin, lower-cased. Unreadable or missing: nothing is allowed."""
    try:
        text = (Path(pin_root or DEFAULT_PIN_ROOT) / PIN_NAME).read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    hosts = (line.split("#", 1)[0].strip().lower().rstrip(".") for line in text.splitlines())
    return frozenset(host for host in hosts if host)


def host_allowed(host: str, allow: frozenset[str]) -> bool:
    """An exact name, or a subdomain of a ``*.name`` entry. Never an address."""
    name = str(host or "").strip().lower().rstrip(".")
    if not name:
        return False
    if name in allow:
        return True
    return any(entry.startswith("*.") and name.endswith(entry[1:]) for entry in allow)


def egress_env(pin_root: Path | None = None) -> dict[str, str]:
    """The proxy settings a caged process needs, once the fence is pinned; else none."""
    if not (Path(pin_root or DEFAULT_PIN_ROOT) / PIN_NAME).is_file():
        return {}
    url = f"http://127.0.0.1:{PORT}"
    return {"HTTPS_PROXY": url, "HTTP_PROXY": url, "NO_PROXY": "127.0.0.1,localhost,::1"}


def _split_target(target: str) -> tuple[str, int] | None:
    if target.startswith("["):  # [v6]:port
        host, _, rest = target[1:].partition("]")
        port = rest.removeprefix(":")
    else:
        host, _, port = target.rpartition(":")
    try:
        return host, int(port)
    except ValueError:
        return None


async def _reply(writer: asyncio.StreamWriter, status: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
    try:
        await writer.drain()
    finally:
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


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    pin_root: Path | None,
    ports: frozenset[int],
    note: Callable[[str], object],
) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), _HEAD_TIMEOUT_S)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        writer.close()
        return
    method, _, rest = head.decode("latin-1").partition(" ")
    if method.upper() != "CONNECT":
        await _reply(writer, "405 Method Not Allowed")
        return
    target = _split_target(rest.split(" ", 1)[0])
    if target is None or target[1] not in ports or not host_allowed(target[0], load_allowlist(pin_root)):
        note(f"refused a tunnel to {rest.split(' ', 1)[0]}")
        await _reply(writer, "403 Forbidden")
        return
    try:
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(*target), _CONNECT_TIMEOUT_S)
    except (OSError, asyncio.TimeoutError):
        await _reply(writer, "502 Bad Gateway")
        return
    writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await writer.drain()
    await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))


async def serve(
    host: str = "127.0.0.1",
    port: int = PORT,
    *,
    pin_root: Path | None = None,
    ports: frozenset[int] = ALLOWED_PORTS,
    log: Callable[[str], object] | None = None,
) -> asyncio.AbstractServer:
    """Start listening. Loopback only: anything else would open the fence to the LAN."""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError(f"the egress proxy listens on loopback only, not {host}")
    note = log or globals()["log"].info

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle(reader, writer, pin_root=pin_root, ports=ports, note=note)

    return await asyncio.start_server(handle, host, port, limit=_MAX_HEAD)


def start_in_thread(*, pin_root: Path | None = None, log: Callable[[str], object] | None = None) -> threading.Thread:
    """Run the proxy on its own event loop, in a daemon thread of the calling service."""

    def run() -> None:
        async def main() -> None:
            server = await serve(pin_root=pin_root, log=log)
            async with server:
                await server.serve_forever()

        asyncio.run(main())

    thread = threading.Thread(target=run, name="egress-proxy", daemon=True)
    thread.start()
    return thread


__all__ = ["PIN_NAME", "PORT", "egress_env", "host_allowed", "load_allowlist", "serve", "start_in_thread"]
