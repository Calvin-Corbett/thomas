import io
import json

import pytest


@pytest.mark.asyncio
async def test_gateway_restart_success(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()

    called = {}

    class FakeGateway:
        async def restart(self, gateway: str = "default", force: bool = False) -> None:
            called["gateway"] = gateway
            called["force"] = force

    app["gateway"] = FakeGateway()

    # Make the test resilient even if create_app doesn't auto-discover this module.
    mod.setup_routes(app)

    client = await aiohttp_client(app)
    resp = await client.post("/gateway/restart", json={"gateway": "alpha", "force": True})
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    assert data["gateway"] == "alpha"
    assert data["status"] == "restart_requested"
    assert data["method"] in ("controller", "command")
    assert called == {"gateway": "alpha", "force": True}


@pytest.mark.asyncio
async def test_gateway_restart_invalid_input(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()

    class FakeGateway:
        async def restart(self, gateway: str = "default", force: bool = False) -> None:
            return None

    app["gateway"] = FakeGateway()
    mod.setup_routes(app)

    client = await aiohttp_client(app)
    resp = await client.post("/gateway/restart", json={"gateway": "alpha", "force": "nope"})
    assert resp.status == 400
    data = await resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_gateway_restart_missing_config(aiohttp_client, monkeypatch):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()

    # Remove any potential gateway hooks/config to force missing_config deterministically.
    for key in (
        "gateway_controller",
        "gateway",
        "gateway_manager",
        "gateway_service",
        "gateway_runtime",
        "gateway_restart_command",
    ):
        app.pop(key, None)

    cfg = app.get("config")
    if isinstance(cfg, dict):
        cfg.pop("gateway_restart_command", None)
        cfg.pop("gateway_restart_cmd", None)

    monkeypatch.delenv("THOMAS_GATEWAY_RESTART_COMMAND", raising=False)

    mod.setup_routes(app)

    client = await aiohttp_client(app)
    resp = await client.post("/gateway/restart", json={})
    assert resp.status == 500
    data = await resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "missing_config"


@pytest.mark.asyncio
async def test_gateway_restart_external_failure(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()

    class FakeGateway:
        async def restart(self, gateway: str = "default", force: bool = False) -> None:
            raise RuntimeError("boom")

    app["gateway"] = FakeGateway()
    mod.setup_routes(app)

    client = await aiohttp_client(app)
    resp = await client.post("/gateway/restart", json={"gateway": "alpha"})
    assert resp.status == 502
    data = await resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "external_failure"


@pytest.mark.asyncio
async def test_gateway_restart_schema_endpoint(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()
    mod.setup_routes(app)
    client = await aiohttp_client(app)

    resp = await client.get("/gateway/restart/schema")
    assert resp.status == 200
    data = await resp.json()
    assert data["path"] == "/gateway/restart"
    assert data["method"] == "POST"


def test_cli_json_output():
    from thomas.cli.commands.gateway import p127_gateway_restart_command as cmd  # type: ignore

    async def fake_requester(server_url, payload):
        return {
            "ok": True,
            "gateway": payload.get("gateway", "default"),
            "status": "restart_requested",
            "method": "controller",
            "message": "Gateway restart requested.",
        }

    out = io.StringIO()
    rc = cmd.run(
        ["--server-url", "http://example", "--gateway", "alpha", "--json"],
        _requester=fake_requester,
        _out=out,
    )
    assert rc == 0
    parsed = __import__("json").loads(out.getvalue().strip())
    assert parsed["ok"] is True
    assert parsed["gateway"] == "alpha"
