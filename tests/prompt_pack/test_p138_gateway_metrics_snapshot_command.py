import asyncio
import os
from typing import Tuple
import argparse

from aiohttp import ClientSession, web

from thomas.server.routes.gateway import p138_gateway_metrics_snapshot_command as route_mod
from thomas.cli.commands.gateway import p138_gateway_metrics_snapshot_command as cli_mod


async def _start_app(app: web.Application) -> Tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    assert site._server is not None
    sock = site._server.sockets[0]
    port = sock.getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def _run(coro):
    return asyncio.run(coro)


def _register_routes(app: web.Application) -> None:
    if hasattr(route_mod, "register"):
        route_mod.register(app)
        return
    routes = getattr(route_mod, "ROUTES", getattr(route_mod, "routes"))
    app.add_routes(routes)


def test_snapshot_success_via_app_hook():
    async def _test():
        app = web.Application()

        async def snapshotter(*, reset: bool, window_seconds: int | None):
            return {"requests_total": 123, "reset": reset, "window_seconds": window_seconds}

        key = getattr(route_mod, "SNAPSHOTTER_APP_KEY", "gateway_metrics_snapshotter")
        app[key] = snapshotter
        _register_routes(app)

        runner = None
        async with ClientSession() as session:
            try:
                runner, base = await _start_app(app)
                url = base + "/v1/gateway/metrics/snapshot"
                async with session.post(url, json={"reset": True, "window_seconds": 60}) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["ok"] is True
                    assert data["snapshot"]["requests_total"] == 123
                    assert data["snapshot"]["reset"] is True
                    assert data["snapshot"]["window_seconds"] == 60
            finally:
                if runner is not None:
                    await runner.cleanup()

    _run(_test())


def test_snapshot_invalid_input_rejected():
    async def _test():
        app = web.Application()

        async def snapshotter(*, reset: bool, window_seconds: int | None):
            return {"ok": True}

        key = getattr(route_mod, "SNAPSHOTTER_APP_KEY", "gateway_metrics_snapshotter")
        app[key] = snapshotter
        _register_routes(app)

        runner = None
        async with ClientSession() as session:
            try:
                runner, base = await _start_app(app)
                url = base + "/v1/gateway/metrics/snapshot"
                async with session.post(url, json={"window_seconds": 0}) as resp:
                    assert resp.status == 400
                    data = await resp.json()
                    assert data["ok"] is False
                    assert data["error"]["code"] == "invalid_request"
            finally:
                if runner is not None:
                    await runner.cleanup()

    _run(_test())


def test_snapshot_missing_config_is_deterministic_error():
    async def _test():
        app = web.Application()
        _register_routes(app)

        runner = None
        async with ClientSession() as session:
            try:
                runner, base = await _start_app(app)
                url = base + "/v1/gateway/metrics/snapshot"
                async with session.get(url) as resp:
                    assert resp.status == 500
                    data = await resp.json()
                    assert data["ok"] is False
                    assert data["error"]["code"] == "missing_config"
            finally:
                if runner is not None:
                    await runner.cleanup()

    _run(_test())


def test_snapshot_success_via_external_gateway_endpoint():
    async def _test():
        upstream = web.Application()

        async def upstream_snapshot(request: web.Request) -> web.Response:
            return web.json_response({"requests_total": 7, "window_seconds": request.query.get("window_seconds")})

        upstream.router.add_get("/metrics/snapshot", upstream_snapshot)

        upstream_runner = None
        app_runner = None
        async with ClientSession() as session:
            try:
                upstream_runner, upstream_base = await _start_app(upstream)

                app = web.Application()
                # Put config in the most common spot.
                app["config"] = {"gateway_metrics_url": upstream_base + "/metrics/snapshot"}
                _register_routes(app)

                app_runner, base = await _start_app(app)

                url = base + "/v1/gateway/metrics/snapshot"
                async with session.get(url, params={"window_seconds": "30"}) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["ok"] is True
                    assert data["snapshot"]["requests_total"] == 7
            finally:
                if app_runner is not None:
                    await app_runner.cleanup()
                if upstream_runner is not None:
                    await upstream_runner.cleanup()

    _run(_test())


def test_snapshot_external_unreachable_is_deterministic_error():
    async def _test():
        app = web.Application()
        app["config"] = {
            "gateway_metrics_url": "http://127.0.0.1:1/metrics/snapshot",
            "gateway_metrics_timeout_seconds": 1,
        }
        _register_routes(app)

        runner = None
        async with ClientSession() as session:
            try:
                runner, base = await _start_app(app)
                url = base + "/v1/gateway/metrics/snapshot"
                async with session.get(url) as resp:
                    assert resp.status == 502
                    data = await resp.json()
                    assert data["ok"] is False
                    assert data["error"]["code"] == "gateway_unreachable"
            finally:
                if runner is not None:
                    await runner.cleanup()

    _run(_test())


def test_cli_json_output_and_exit_codes(capsys):
    async def _test():
        app = web.Application()

        async def snapshotter(*, reset: bool, window_seconds: int | None):
            return {"requests_total": 9}

        key = getattr(route_mod, "SNAPSHOTTER_APP_KEY", "gateway_metrics_snapshotter")
        app[key] = snapshotter
        _register_routes(app)

        runner = None
        try:
            runner, base = await _start_app(app)
            os.environ["THOMAS_SERVER_URL"] = base

            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            cli_mod.add_parser(sub)

            args = parser.parse_args(["gateway-metrics-snapshot", "--json"])
            rc = await asyncio.to_thread(cli_mod.run, args)
            assert rc == 0

            out = capsys.readouterr().out.strip()
            parsed = __import__("json").loads(out)
            assert parsed["ok"] is True
            assert parsed["snapshot"]["requests_total"] == 9

            # Failure path: point to a dead server
            os.environ["THOMAS_SERVER_URL"] = "http://127.0.0.1:1"
            args2 = parser.parse_args(["gateway-metrics-snapshot", "--json"])
            rc2 = await asyncio.to_thread(cli_mod.run, args2)
            assert rc2 == 1
        finally:
            if runner is not None:
                await runner.cleanup()

    _run(_test())

