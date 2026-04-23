import asyncio
from contextlib import asynccontextmanager

import pytest
from aiohttp import ClientSession, web

from thomas.cli.commands.gateway.p130_gateway_probe_command import run_probe
from thomas.server.routes.gateway.p130_gateway_probe_command import (
    GatewayProbeException,
    probe_gateway,
    resolve_gateway_target,
    routes as gateway_routes,
)


@asynccontextmanager
async def run_test_server(app: web.Application):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()

    port = None
    try:
        addresses = runner.addresses
        if addresses:
            port = addresses[0][1]
    except Exception:
        port = None

    if port is None:
        sockets = site._server.sockets  # type: ignore[attr-defined]
        port = sockets[0].getsockname()[1]

    base_url = f"http://127.0.0.1:{port}"
    try:
        yield base_url
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_probe_gateway_success():
    app = web.Application()

    async def ok(request):
        return web.Response(text="ok")

    app.router.add_get("/", ok)

    async with run_test_server(app) as base_url:
        result = await probe_gateway(target=base_url, timeout_s=1.0, path="/")

    assert result.ok is True
    assert result.status_code == 200
    assert isinstance(result.latency_ms, int)


@pytest.mark.asyncio
async def test_probe_gateway_bad_status():
    app = web.Application()

    async def fail(request):
        return web.Response(status=503, text="nope")

    app.router.add_get("/fail", fail)

    async with run_test_server(app) as base_url:
        result = await probe_gateway(target=base_url, timeout_s=1.0, path="/fail")

    assert result.ok is False
    assert result.status_code == 503
    assert result.error
    assert result.error["code"] == "bad_status"


@pytest.mark.asyncio
async def test_probe_gateway_timeout_is_deterministic():
    app = web.Application()

    async def slow(request):
        await asyncio.sleep(0.5)
        return web.Response(text="finally")

    app.router.add_get("/slow", slow)

    async with run_test_server(app) as base_url:
        result = await probe_gateway(target=base_url, timeout_s=0.05, path="/slow")

    assert result.ok is False
    assert result.error
    assert result.error["code"] == "timeout"


def test_resolve_gateway_target_missing_config():
    with pytest.raises(GatewayProbeException) as ei:
        resolve_gateway_target(environ={})

    assert ei.value.code == "missing_config"


def test_resolve_gateway_target_invalid_target():
    with pytest.raises(GatewayProbeException) as ei:
        resolve_gateway_target(explicit_target="not-a-url", environ={})

    assert ei.value.code == "invalid_target"


@pytest.mark.asyncio
async def test_server_route_returns_json_success():
    target_app = web.Application()

    async def ok(request):
        return web.Response(text="ok")

    target_app.router.add_get("/", ok)

    async with run_test_server(target_app) as target_url:
        api_app = web.Application()
        api_app.add_routes(gateway_routes)

        async with run_test_server(api_app) as api_url:
            async with ClientSession() as session:
                resp = await session.post(
                    f"{api_url}/probe",
                    json={"target": target_url, "timeout_s": 1.0, "path": "/"},
                )
                assert resp.status == 200
                data = await resp.json()

    assert data["ok"] is True
    assert data["target"] == target_url


@pytest.mark.asyncio
async def test_server_route_returns_json_error_on_invalid_json():
    api_app = web.Application()
    api_app.add_routes(gateway_routes)

    async with run_test_server(api_app) as api_url:
        async with ClientSession() as session:
            resp = await session.post(
                f"{api_url}/probe",
                data="not-json",
                headers={"Content-Type": "application/json"},
            )
            assert resp.status == 400
            data = await resp.json()

    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_cli_run_probe_supports_env_override(monkeypatch):
    target_app = web.Application()

    async def ok(request):
        return web.Response(text="ok")

    target_app.router.add_get("/", ok)

    async with run_test_server(target_app) as target_url:
        monkeypatch.setenv("THOMAS_GATEWAY_URL", target_url)
        result = await run_probe(timeout_s=1.0)

    assert result.ok is True
    assert result.target == target_url
