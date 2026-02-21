from __future__ import annotations

import asyncio
import json
import sys

import pytest
from aiohttp import web
from typer.testing import CliRunner

from thomas.cli.commands.nodes.p052_nodes_cli_integration_and_parity_tests import app as nodes_cli_app
from thomas.nodes.p052_nodes_cli_integration_and_parity_tests import (
    NodesCliIntegrationError,
    NodesCliRequest,
    fetch_nodes,
    run_parity_tests,
)


async def _start_test_server(app: web.Application) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets  # type: ignore[union-attr]
    assert sockets, "Expected at least one listening socket"
    port = sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


async def _stop_test_server(runner: web.AppRunner) -> None:
    await runner.cleanup()


def test_missing_base_url_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_BASE_URL", raising=False)
    monkeypatch.delenv("THOMAS_SERVER_URL", raising=False)
    monkeypatch.delenv("THOMAS_URL", raising=False)

    with pytest.raises(NodesCliIntegrationError) as exc:
        asyncio.run(fetch_nodes(NodesCliRequest(base_url=None, nodes_path="/nodes")))

    assert exc.value.code == "missing_config"
    assert "base URL" in exc.value.message


def test_invalid_base_url_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_BASE_URL", raising=False)
    monkeypatch.delenv("THOMAS_SERVER_URL", raising=False)
    monkeypatch.delenv("THOMAS_URL", raising=False)

    with pytest.raises(NodesCliIntegrationError) as exc:
        asyncio.run(fetch_nodes(NodesCliRequest(base_url="localhost:9999", nodes_path="/nodes")))

    assert exc.value.code == "invalid_input"


def test_invalid_nodes_path_is_deterministic() -> None:
    with pytest.raises(NodesCliIntegrationError) as exc:
        asyncio.run(fetch_nodes(NodesCliRequest(base_url="http://127.0.0.1:1", nodes_path="   ")))
    assert exc.value.code == "invalid_input"


def test_external_failure_is_deterministic() -> None:
    async def _run() -> None:
        app = web.Application()

        async def nodes_handler(_: web.Request) -> web.Response:
            return web.Response(status=500, text="boom")

        app.router.add_get("/nodes", nodes_handler)

        runner, base_url = await _start_test_server(app)
        try:
            with pytest.raises(NodesCliIntegrationError) as exc:
                await fetch_nodes(NodesCliRequest(base_url=base_url, nodes_path="/nodes", timeout_s=2.0))
            assert exc.value.code == "external_failure"
            assert exc.value.details.get("status") == 500
        finally:
            await _stop_test_server(runner)

    asyncio.run(_run())


def test_parity_rejects_invalid_node_entries() -> None:
    async def _run() -> None:
        app = web.Application()

        async def nodes_handler(_: web.Request) -> web.Response:
            # dict without id/name should be rejected by parity.
            return web.json_response([{}])

        app.router.add_get("/nodes", nodes_handler)

        runner, base_url = await _start_test_server(app)
        try:
            with pytest.raises(NodesCliIntegrationError) as exc:
                await run_parity_tests(NodesCliRequest(base_url=base_url, nodes_path="/nodes", timeout_s=2.0))
            assert exc.value.code == "invalid_response"
        finally:
            await _stop_test_server(runner)

    asyncio.run(_run())


def test_success_fetch_and_cli_json_output() -> None:
    async def _run() -> None:
        app = web.Application()

        async def nodes_handler(_: web.Request) -> web.Response:
            return web.json_response([{"id": "n1", "name": "node-1", "status": "ready"}])

        app.router.add_get("/nodes", nodes_handler)

        runner, base_url = await _start_test_server(app)
        try:
            result = await run_parity_tests(NodesCliRequest(base_url=base_url, nodes_path="/nodes", timeout_s=2.0))
            assert result.ok is True
            assert result.nodes and result.nodes[0]["id"] == "n1"

            runner_cli = CliRunner()
            r = await asyncio.to_thread(
                runner_cli.invoke,
                nodes_cli_app,
                ["list", "--base-url", base_url, "--nodes-path", "/nodes", "--json"],
            )
            assert r.exit_code == 0, r.output
            payload = json.loads(r.output)
            assert payload["ok"] is True
            assert payload["nodes"][0]["name"] == "node-1"

            r2 = await asyncio.to_thread(
                runner_cli.invoke,
                nodes_cli_app,
                ["parity", "--base-url", base_url, "--nodes-path", "/nodes", "--json"],
            )
            assert r2.exit_code == 0, r2.output
            payload2 = json.loads(r2.output)
            assert payload2["ok"] is True
        finally:
            await _stop_test_server(runner)

    asyncio.run(_run())


def test_cli_failure_json_mode_is_machine_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_BASE_URL", raising=False)
    monkeypatch.delenv("THOMAS_SERVER_URL", raising=False)
    monkeypatch.delenv("THOMAS_URL", raising=False)

    runner_cli = CliRunner()
    r = runner_cli.invoke(nodes_cli_app, ["list", "--json"])
    assert r.exit_code != 0
    payload = json.loads(r.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"


def test_wiring_registers_under_thomas_cli_main() -> None:
    # Ensure our import-time hook does not explode and the main app can see nodes/devices.
    # We use the stub main.py in this prompt pack test environment.
    if "thomas.cli.main" in sys.modules:
        del sys.modules["thomas.cli.main"]

    import thomas.cli.main as main_mod  # noqa: F401

    runner_cli = CliRunner()
    r = runner_cli.invoke(main_mod.app, ["--help"])
    assert r.exit_code == 0
    # Typer help output should mention the commands if registered.
    assert "nodes" in r.output
    assert "devices" in r.output
