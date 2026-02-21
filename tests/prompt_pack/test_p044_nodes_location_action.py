import asyncio
import json

import pytest
import typer
from typer.testing import CliRunner

from thomas.nodes.p044_nodes_location_action import (
    NodesLocationActionError,
    NodesLocationActionInput,
    get_node_location,
)
from thomas.cli.commands.nodes import p044_nodes_location_action as cli_mod


class StubInvoker:
    async def node_invoke(self, node: str, command: str, params, *, timeout_ms=None, idempotency_key=None):
        assert node == "node-1"
        assert command == "location.get"
        assert params["desiredAccuracy"] == "precise"
        assert params["maxAgeMs"] == 123
        assert params["timeoutMs"] == 456
        return {
            "lat": 48.20849,
            "lon": 16.37208,
            "accuracyMeters": 12.5,
            "timestamp": "2026-01-03T12:34:56.000Z",
            "isPrecise": True,
            "source": "gps",
        }


class ErrorInvoker:
    async def node_invoke(self, node: str, command: str, params, *, timeout_ms=None, idempotency_key=None):
        return {"ok": False, "error": {"code": "LOCATION_DISABLED", "message": "Location sharing is disabled."}}


def test_location_action_success_parses_payload():
    inp = NodesLocationActionInput(
        node="node-1",
        accuracy="precise",
        max_age_ms=123,
        location_timeout_ms=456,
        invoke_timeout_ms=789,
    )
    out = asyncio.run(get_node_location(inp, invoker=StubInvoker()))
    assert out.lat == pytest.approx(48.20849)
    assert out.lon == pytest.approx(16.37208)
    assert out.accuracy_meters == pytest.approx(12.5)
    assert out.timestamp == "2026-01-03T12:34:56.000Z"
    assert out.is_precise is True
    assert out.source == "gps"


def test_location_action_rejects_invalid_accuracy():
    with pytest.raises(NodesLocationActionError) as ei:
        asyncio.run(
            get_node_location(
                NodesLocationActionInput(
                    node="node-1",
                    accuracy="nope",  # type: ignore[arg-type]
                ),
                invoker=StubInvoker(),
            )
        )
    assert ei.value.code == "invalid_input"
    assert "accuracy must be one of" in ei.value.message


def test_location_action_propagates_node_error_code():
    with pytest.raises(NodesLocationActionError) as ei:
        asyncio.run(
            get_node_location(
                NodesLocationActionInput(node="node-1", accuracy="balanced"),
                invoker=ErrorInvoker(),
            )
        )
    assert ei.value.code == "LOCATION_DISABLED"
    assert "disabled" in ei.value.message.lower()


def test_location_action_missing_invoker_is_deterministic():
    with pytest.raises(NodesLocationActionError) as ei:
        asyncio.run(get_node_location(NodesLocationActionInput(node="node-1"), invoker=None))
    assert ei.value.code == "missing_config"


def test_location_action_rejects_out_of_range_lat_lon():
    class BadPayloadInvoker:
        async def node_invoke(self, node: str, command: str, params, *, timeout_ms=None, idempotency_key=None):
            return {"lat": 999, "lon": 0, "timestamp": 1700000000000}
    with pytest.raises(NodesLocationActionError) as ei:
        asyncio.run(get_node_location(NodesLocationActionInput(node="node-1"), invoker=BadPayloadInvoker()))
    assert ei.value.code == "invalid_response"
    assert "lat out of range" in ei.value.message


def test_location_action_accepts_callable_invoker():
    async def inv(node: str, command: str, params, timeout_ms=None, idempotency_key=None):
        assert node == "node-1"
        assert command == "location.get"
        return {"latitude": "1.25", "longitude": "2.5", "timestamp": "2026-02-01T00:00:00Z"}

    out = asyncio.run(get_node_location({"node": "node-1"}, invoker=inv))
    assert out.lat == pytest.approx(1.25)
    assert out.lon == pytest.approx(2.5)


def test_cli_location_json_success(monkeypatch):
    runner = CliRunner()

    def fake_resolve(_ctx):
        return StubInvoker()

    monkeypatch.setattr(cli_mod, "_resolve_invoker", fake_resolve)

    root = typer.Typer()
    nodes = typer.Typer()
    root.add_typer(nodes, name="nodes")
    cli_mod.register(nodes)

    result = runner.invoke(
        root,
        [
            "nodes",
            "location",
            "get",
            "--node",
            "node-1",
            "--accuracy",
            "precise",
            "--max-age",
            "123",
            "--location-timeout",
            "456",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["result"]["lat"] == pytest.approx(48.20849)


def test_cli_location_json_failure(monkeypatch):
    runner = CliRunner()

    def fake_resolve(_ctx):
        return ErrorInvoker()

    monkeypatch.setattr(cli_mod, "_resolve_invoker", fake_resolve)

    root = typer.Typer()
    nodes = typer.Typer()
    root.add_typer(nodes, name="nodes")
    cli_mod.register(nodes)

    result = runner.invoke(root, ["nodes", "location", "get", "--node", "node-1", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "LOCATION_DISABLED"
