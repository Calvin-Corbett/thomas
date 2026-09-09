from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import pytest_asyncio
from aiohttp import WSMsgType, web
from click.testing import CliRunner

from thomas.cli.commands.gateway.p133_gateway_health_detailed_payload import gateway_health_detailed_payload
from thomas.server.routes.gateway.p133_gateway_health_detailed_payload import (
    GatewayHealthConfigError,
    GatewayHealthDetailedRequest,
    GatewayHealthExternalError,
    GatewayHealthInputError,
    fetch_gateway_health_detailed,
)


async def _start_fake_gateway(*, port: int, health_ok: bool) -> tuple[web.AppRunner, str]:
    app = web.Application()

    async def ws_handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Pre-connect challenge (some gateways do this).
        await ws.send_json(
            {
                "type": "event",
                "event": "connect.challenge",
                "payload": {"nonce": "abc123", "ts": 1737264000000},
            }
        )

        # Expect connect.
        msg = await ws.receive()
        assert msg.type == WSMsgType.TEXT
        connect_req = json.loads(msg.data)
        assert connect_req["type"] == "req"
        assert connect_req["method"] == "connect"
        connect_id = connect_req["id"]

        await ws.send_json(
            {
                "type": "res",
                "id": connect_id,
                "ok": True,
                "payload": {"type": "hello-ok", "protocol": 3},
            }
        )

        # Expect health.
        msg = await ws.receive()
        assert msg.type == WSMsgType.TEXT
        health_req = json.loads(msg.data)
        assert health_req["type"] == "req"
        assert health_req["method"] == "health"
        health_id = health_req["id"]

        if health_ok:
            await ws.send_json(
                {
                    "type": "res",
                    "id": health_id,
                    "ok": True,
                    "payload": {
                        "status": "ok",
                        "channels": {"dummy": {"reachable": True}},
                        "session_store": {"count": 0},
                    },
                }
            )
        else:
            await ws.send_json(
                {
                    "type": "res",
                    "id": health_id,
                    "ok": False,
                    "error": {"code": "probe_failed", "message": "simulated failure"},
                }
            )

        await ws.close()
        return ws

    app.router.add_get("/ws", ws_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner, f"ws://127.0.0.1:{port}/ws"


@pytest_asyncio.fixture
async def fake_gateway_ok(unused_tcp_port: int) -> str:
    runner, url = await _start_fake_gateway(port=unused_tcp_port, health_ok=True)
    try:
        yield url
    finally:
        await runner.cleanup()


@pytest_asyncio.fixture
async def fake_gateway_fail(unused_tcp_port_factory: Any) -> str:
    port = unused_tcp_port_factory()
    runner, url = await _start_fake_gateway(port=port, health_ok=False)
    try:
        yield url
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_gateway_health_success(fake_gateway_ok: str) -> None:
    req = GatewayHealthDetailedRequest(url=fake_gateway_ok, token="t0k3n", timeout_ms=2000)
    result = await fetch_gateway_health_detailed(req)
    payload = result.to_dict()

    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["gateway"]["url"] == fake_gateway_ok
    assert payload["snapshot"]["status"] == "ok"
    assert payload["gateway"]["protocol"] == 3
    assert isinstance(payload["duration_ms"], int)
    assert payload["service"]["name"] == "thomas"


@pytest.mark.asyncio
async def test_fetch_gateway_health_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_GATEWAY_URL", raising=False)
    monkeypatch.delenv("THOMAS_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("THOMAS_GATEWAY_PASSWORD", raising=False)

    with pytest.raises(GatewayHealthConfigError) as exc:
        await fetch_gateway_health_detailed(GatewayHealthDetailedRequest())

    assert exc.value.code == "gateway_not_configured"


@pytest.mark.asyncio
async def test_fetch_gateway_health_invalid_timeout() -> None:
    with pytest.raises(GatewayHealthInputError) as exc:
        await fetch_gateway_health_detailed(
            GatewayHealthDetailedRequest(url="ws://127.0.0.1:1/ws", token="x", timeout_ms=0)
        )

    assert exc.value.code == "invalid_timeout"


@pytest.mark.asyncio
async def test_fetch_gateway_health_invalid_url_scheme() -> None:
    with pytest.raises(GatewayHealthInputError) as exc:
        await fetch_gateway_health_detailed(
            GatewayHealthDetailedRequest(url="http://127.0.0.1:1/ws", token="x", timeout_ms=1000)
        )

    assert exc.value.code == "invalid_url"


@pytest.mark.asyncio
async def test_fetch_gateway_health_external_failure(fake_gateway_fail: str) -> None:
    req = GatewayHealthDetailedRequest(url=fake_gateway_fail, token="t0k3n", timeout_ms=2000)
    with pytest.raises(GatewayHealthExternalError) as exc:
        await fetch_gateway_health_detailed(req)

    assert exc.value.code == "gateway_health_failed"


@pytest.mark.asyncio
async def test_cli_json_success(fake_gateway_ok: str) -> None:
    runner = CliRunner()
    result = await asyncio.to_thread(
        runner.invoke,
        gateway_health_detailed_payload,
        ["--url", fake_gateway_ok, "--token", "t0k3n", "--timeout", "2000", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["gateway"]["url"] == fake_gateway_ok


@pytest.mark.asyncio
async def test_cli_json_ambiguous_auth(fake_gateway_ok: str) -> None:
    runner = CliRunner()
    result = await asyncio.to_thread(
        runner.invoke,
        gateway_health_detailed_payload,
        ["--url", fake_gateway_ok, "--token", "a", "--password", "b", "--json"],
    )
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "ambiguous_auth"
