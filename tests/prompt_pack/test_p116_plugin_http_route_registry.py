import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from thomas.cli.commands.plugins.p116_plugin_http_route_registry import cli as routes_cli
from thomas.plugins.p116_plugin_http_route_registry import (
    DuplicateRouteError,
    InvalidRouteInputError,
    PluginHttpRouteRegistry,
    get_default_registry,
)


@pytest.fixture()
def isolated_default_registry():
    """Isolate the process-global registry for this test.

    The implementation under test provides a process-global default registry so plugins
    can register routes at runtime. Tests should not leak state across the suite, so we
    snapshot + restore.
    """
    reg = get_default_registry()
    snapshot = reg.list()
    reg.clear()
    try:
        yield reg
    finally:
        reg.clear()
        for r in snapshot:
            reg.register(plugin_id=r.plugin_id, path=r.path, source=r.source)


def test_registry_register_and_list_normalizes_and_sorts():
    reg = PluginHttpRouteRegistry()
    reg.register(plugin_id="plugin-b", path="bar")
    reg.register(plugin_id="plugin-a", path="/foo", source="unit-test")

    routes = reg.list()
    assert [r.path for r in routes] == ["/bar", "/foo"]
    assert routes[0].plugin_id == "plugin-b"
    assert routes[1].plugin_id == "plugin-a"
    assert routes[1].source == "unit-test"

    filtered = reg.list(plugin_id="plugin-a")
    assert [r.path for r in filtered] == ["/foo"]


def test_registry_duplicate_path_raises_deterministic_error():
    reg = PluginHttpRouteRegistry()
    reg.register(plugin_id="a", path="/dup")

    with pytest.raises(DuplicateRouteError) as exc:
        reg.register(plugin_id="b", path="dup")  # normalizes to /dup

    err = exc.value
    assert err.code == "duplicate_route"
    assert err.details["path"] == "/dup"
    assert err.details["existing_plugin_id"] == "a"


def test_registry_invalid_input_raises_deterministic_error():
    reg = PluginHttpRouteRegistry()

    with pytest.raises(InvalidRouteInputError) as exc:
        reg.register(plugin_id="   ", path="/x")

    assert exc.value.code == "invalid_input"

    with pytest.raises(InvalidRouteInputError):
        reg.register(plugin_id="a", path="/has space")


def test_cli_json_output_includes_routes(isolated_default_registry):
    isolated_default_registry.register(plugin_id="demo", path="hello", source="test")

    runner = CliRunner()
    result = runner.invoke(routes_cli, ["--json"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["count"] == 1
    assert payload["routes"][0]["plugin_id"] == "demo"
    assert payload["routes"][0]["path"] == "/hello"
    assert payload["routes"][0]["source"] == "test"


def test_cli_schema_output_is_valid_json_schema():
    runner = CliRunner()
    result = runner.invoke(routes_cli, ["--schema"])
    assert result.exit_code == 0, result.output

    schema = json.loads(result.output)
    assert schema.get("$schema")
    assert "oneOf" in schema


def test_cli_missing_config_is_deterministic(tmp_path: Path):
    missing = tmp_path / "nope.json"

    runner = CliRunner()
    result = runner.invoke(routes_cli, ["--json", "--config", str(missing)])
    assert result.exit_code == 1, result.output

    payload = json.loads(result.output)
    assert payload["error"]["code"] == "missing_config"
    assert str(missing) in payload["error"]["message"]


def test_cli_rejects_schema_and_json_together():
    runner = CliRunner()
    result = runner.invoke(routes_cli, ["--json", "--schema"])
    assert result.exit_code == 2, result.output

    payload = json.loads(result.output)
    assert payload["error"]["code"] == "invalid_input"


def test_cli_loads_routes_from_config(tmp_path: Path):
    cfg = tmp_path / "routes.json"
    cfg.write_text(
        json.dumps(
            {
                "plugin_http_routes": [
                    {"plugin_id": "acme", "path": "webhook", "source": "cfg"},
                    {"plugin_id": "acme", "path": "/status"},
                ]
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(routes_cli, ["--json", "--config", str(cfg), "--plugin-id", "acme"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    paths = [r["path"] for r in payload["routes"]]
    assert paths == ["/status", "/webhook"]


def test_cli_invalid_json_config_is_deterministic(tmp_path: Path):
    cfg = tmp_path / "bad.json"
    cfg.write_text("{not json", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(routes_cli, ["--json", "--config", str(cfg)])
    assert result.exit_code == 1, result.output

    payload = json.loads(result.output)
    assert payload["error"]["code"] == "invalid_config"
