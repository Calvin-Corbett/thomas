import asyncio
import io
import json
import sys

import pytest

pytest.importorskip("aiohttp.pytest_plugin")


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


async def test_gateway_restart_remote_mode_requires_api_token(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()
    app["gateway_restart_access_mode"] = "remote"
    app["gateway_restart_api_token"] = "secret"

    class FakeGateway:
        async def restart(self, gateway: str = "default", force: bool = False) -> None:
            return None

    app["gateway"] = FakeGateway()
    mod.setup_routes(app)
    client = await aiohttp_client(app)

    missing = await client.post("/gateway/restart", json={})
    assert missing.status == 401
    missing_data = await missing.json()
    assert missing_data["ok"] is False
    assert missing_data["error"]["code"] == "access_denied"

    ok = await client.post(
        "/gateway/restart",
        json={"gateway": "alpha"},
        headers={"Authorization": "Bearer secret"},
    )
    assert ok.status == 200
    ok_data = await ok.json()
    assert ok_data["ok"] is True


async def test_gateway_restart_rate_limited(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()
    app["gateway_restart_access_mode"] = "remote"
    app["gateway_restart_api_token"] = "secret"
    app["gateway_restart_rate_limit_enabled"] = True
    app["gateway_restart_rate_limit_max_requests"] = 1
    app["gateway_restart_rate_limit_window_seconds"] = 60

    class FakeGateway:
        async def restart(self, gateway: str = "default", force: bool = False) -> None:
            return None

    app["gateway"] = FakeGateway()
    mod.setup_routes(app)
    client = await aiohttp_client(app)
    headers = {"Authorization": "Bearer secret"}

    first = await client.post("/gateway/restart", json={}, headers=headers)
    assert first.status == 200

    second = await client.post("/gateway/restart", json={}, headers=headers)
    assert second.status == 429
    assert second.headers.get("Retry-After")
    data = await second.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "rate_limited"


async def test_gateway_restart_rejects_parallel_restart_requests(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()
    gate = asyncio.Event()

    class FakeGateway:
        async def restart(self, gateway: str = "default", force: bool = False) -> None:
            await gate.wait()

    app["gateway"] = FakeGateway()
    mod.setup_routes(app)
    client = await aiohttp_client(app)

    first_task = asyncio.create_task(client.post("/gateway/restart", json={"gateway": "alpha"}))
    await asyncio.sleep(0.05)
    second = await client.post("/gateway/restart", json={"gateway": "beta"})
    assert second.status == 409
    second_data = await second.json()
    assert second_data["ok"] is False
    assert second_data["error"]["code"] == "restart_in_progress"

    gate.set()
    first = await first_task
    assert first.status == 200


async def test_gateway_restart_defers_until_pending_drains(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()
    app["gateway_restart_deferral_poll_ms"] = 10
    app["gateway_restart_deferral_max_wait_ms"] = 1000

    calls = {"n": 0}

    def pending_count() -> int:
        calls["n"] += 1
        return 1 if calls["n"] < 3 else 0

    called = {}

    class FakeGateway:
        async def restart(self, gateway: str = "default", force: bool = False) -> None:
            called["ok"] = True

    app["gateway"] = FakeGateway()
    app["gateway_restart_pending_count"] = pending_count
    mod.setup_routes(app)
    client = await aiohttp_client(app)

    resp = await client.post("/gateway/restart", json={})
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    assert data["deferral"]["enabled"] is True
    assert data["deferral"]["waited_ms"] >= 0
    assert calls["n"] >= 3
    assert called["ok"] is True


async def test_gateway_restart_command_failure_includes_diagnostics(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()
    app["gateway_restart_command"] = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('boom\\n'); sys.exit(3)",
    ]
    mod.setup_routes(app)
    client = await aiohttp_client(app)

    resp = await client.post("/gateway/restart", json={})
    assert resp.status == 502
    data = await resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "external_failure"
    details = data["error"]["details"]
    assert details["returncode"] == 3
    assert "boom" in details.get("stderr", "")


async def test_gateway_restart_concurrency_soak_rejects_parallel_burst(aiohttp_client):
    from thomas.server.app import create_app  # type: ignore
    from thomas.server.routes.gateway import p127_gateway_restart_command as mod  # type: ignore

    app = create_app()
    app["gateway_restart_rate_limit_enabled"] = False
    gate = asyncio.Event()
    started = asyncio.Event()

    class FakeGateway:
        async def restart(self, gateway: str = "default", force: bool = False) -> None:
            started.set()
            await gate.wait()

    app["gateway"] = FakeGateway()
    mod.setup_routes(app)
    client = await aiohttp_client(app)

    first_task = asyncio.create_task(client.post("/gateway/restart", json={"gateway": "primary"}))
    await asyncio.wait_for(started.wait(), timeout=2.0)

    burst = [
        asyncio.create_task(client.post("/gateway/restart", json={"gateway": f"burst-{i}"}))
        for i in range(10)
    ]

    await asyncio.sleep(0.05)
    gate.set()

    responses = [await first_task] + [await task for task in burst]
    statuses = [resp.status for resp in responses]

    assert statuses.count(200) == 1
    assert statuses.count(409) == 10
    for resp in responses:
        if resp.status == 409:
            body = await resp.json()
            assert body["error"]["code"] == "restart_in_progress"


