"""The cage's one way out forwards to pinned hosts and to nothing else.

Project 4b of docs/superpowers/plans/2026-09-22-caged-server.md. The firewall stops
the cage account reaching anything but loopback; what it may still reach -- the
model providers, PyPI, npm -- it reaches through a proxy that runs as you, listens
only on loopback, and tunnels only to hosts in egress.allow, a pin only an
administrator can change. A missing pin allows nothing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from scripts.cage import egress_proxy as ep
from scripts.cage import shell_runner


def _pin(tmp_path: Path, *hosts: str) -> Path:
    root = tmp_path / "pins"
    root.mkdir(exist_ok=True)
    (root / ep.PIN_NAME).write_text("# model hosts\n" + "\n".join(hosts) + "\n", encoding="utf-8")
    return root


def test_the_allowlist_is_the_pin_and_nothing_else(tmp_path: Path) -> None:
    allow = ep.load_allowlist(_pin(tmp_path, "chatgpt.com", "*.pythonhosted.org"))

    assert ep.host_allowed("chatgpt.com", allow)
    assert ep.host_allowed("ChatGPT.com.", allow)
    assert ep.host_allowed("files.pythonhosted.org", allow)
    for host in ("pythonhosted.org", "evilchatgpt.com", "chatgpt.com.evil.net", "93.184.216.34", ""):
        assert not ep.host_allowed(host, allow), host


def test_no_pin_allows_nothing(tmp_path: Path) -> None:
    assert ep.load_allowlist(tmp_path / "missing") == frozenset()


async def _upstream() -> tuple[asyncio.AbstractServer, int, list[int]]:
    hits: list[int] = []

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        hits.append(1)
        data = await reader.read(100)
        writer.write(b"echo:" + data)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], hits


async def _ask(proxy_port: int, request: bytes) -> tuple[bytes, asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(request)
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    return head, reader, writer


def test_a_pinned_host_is_tunnelled(tmp_path: Path) -> None:
    async def scenario() -> tuple[bytes, bytes]:
        upstream, up_port, _hits = await _upstream()
        proxy = await ep.serve(port=0, pin_root=_pin(tmp_path, "localhost"), ports=frozenset({up_port}))
        target = f"localhost:{up_port}"
        head, reader, writer = await _ask(
            proxy.sockets[0].getsockname()[1], f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode()
        )
        writer.write(b"hello")
        await writer.drain()
        body = await asyncio.wait_for(reader.read(100), 5)
        writer.close()
        proxy.close()
        upstream.close()
        return head, body

    head, body = asyncio.run(scenario())

    assert head.startswith(b"HTTP/1.1 200")
    assert body == b"echo:hello"


def test_an_unpinned_host_or_port_is_refused_without_connecting(tmp_path: Path) -> None:
    async def scenario() -> tuple[list[bytes], list[int], list[str]]:
        upstream, up_port, hits = await _upstream()
        refused: list[str] = []
        pins = _pin(tmp_path, "chatgpt.com", "localhost")
        proxy = await ep.serve(port=0, pin_root=pins, log=refused.append)  # ports: 443 only
        port = proxy.sockets[0].getsockname()[1]
        heads = []
        for target in (f"example.com:{up_port}", f"localhost:{up_port}"):
            head, _reader, writer = await _ask(port, f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
            heads.append(head)
            writer.close()
        proxy.close()
        upstream.close()
        return heads, hits, refused

    heads, hits, refused = asyncio.run(scenario())

    assert all(head.startswith(b"HTTP/1.1 403") for head in heads), heads
    assert hits == [], "a refused tunnel must never reach its target"
    assert len(refused) == 2 and "example.com" in refused[0]


def test_only_tunnels_are_served(tmp_path: Path) -> None:
    async def scenario() -> bytes:
        proxy = await ep.serve(port=0, pin_root=_pin(tmp_path, "localhost"))
        head, _reader, writer = await _ask(
            proxy.sockets[0].getsockname()[1], b"GET http://localhost/ HTTP/1.1\r\nHost: localhost\r\n\r\n"
        )
        writer.close()
        proxy.close()
        return head

    assert asyncio.run(scenario()).startswith(b"HTTP/1.1 405")


def test_the_proxy_listens_only_on_loopback(tmp_path: Path) -> None:
    async def scenario() -> str:
        proxy = await ep.serve(port=0, pin_root=_pin(tmp_path, "localhost"))
        host = proxy.sockets[0].getsockname()[0]
        proxy.close()
        return host

    assert asyncio.run(scenario()) == "127.0.0.1"


def test_the_probe_judges_a_fence_by_what_the_cage_could_reach() -> None:
    from scripts.cage import fence_probe as fp

    unfenced = {"direct": "200", "unlisted": "403", "listed": "200"}
    fenced = {**unfenced, "direct": "000"}

    assert fp.problems(unfenced, fenced=False) == []
    assert fp.problems(fenced, fenced=True) == []
    assert fp.problems(unfenced, fenced=True), "a direct connection that still works is no fence"
    assert fp.problems(fenced, fenced=False), "with no baseline a later failure proves nothing"
    assert fp.problems({**fenced, "listed": "403"}, fenced=True), "a fence that cuts off the models is not kept"
    assert fp.problems({**fenced, "unlisted": "200"}, fenced=True), "an open proxy is no fence"


def test_the_cage_uses_the_proxy_only_once_the_fence_is_pinned(tmp_path: Path) -> None:
    assert ep.egress_env(tmp_path / "missing") == {}
    env = ep.egress_env(_pin(tmp_path, "chatgpt.com"))
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == f"http://127.0.0.1:{ep.PORT}"
    assert "127.0.0.1" in env["NO_PROXY"] and "localhost" in env["NO_PROXY"]
    # The runner is standalone (no imports from thomas or other scripts), so it
    # carries the same two facts itself; they must not drift apart.
    assert shell_runner.EGRESS_PORT == ep.PORT
    assert shell_runner.EGRESS_PIN == ep.DEFAULT_PIN_ROOT / ep.PIN_NAME
