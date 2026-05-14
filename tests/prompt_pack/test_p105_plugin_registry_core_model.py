from __future__ import annotations

import json
import sys
import types

import pytest
from typer.testing import CliRunner


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _install_dummy_plugin(module_name: str) -> None:
    """Install a dummy plugin module in sys.modules for isolated tests."""
    mod = types.ModuleType(module_name)
    mod.PLUGIN = {
        "name": "dummy-plugin",
        "version": "1.2.3",
        "description": "A dummy plugin for tests",
        "tools": [
            {
                "name": "dummy.tool",
                "description": "Does nothing",
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
                "output_schema": {"type": "object", "properties": {}, "additionalProperties": True},
            }
        ],
    }
    sys.modules[module_name] = mod


def test_build_plugin_registry_core_model_from_explicit_modules() -> None:
    from thomas.plugins.p105_plugin_registry_core_model import (
        BuildPluginRegistryRequest,
        build_plugin_registry_core_model,
    )

    module_name = "thomas_test_plugins.dummy"
    _install_dummy_plugin(module_name)

    model = build_plugin_registry_core_model(
        BuildPluginRegistryRequest(plugin_modules=[module_name], include_tools=True, include_failed=True)
    )

    assert model.schema_version
    assert len(model.plugins) == 1

    plugin = model.plugins[0]
    assert plugin.module == module_name
    assert plugin.name == "dummy-plugin"
    assert plugin.version == "1.2.3"
    assert plugin.load_error is None

    assert len(plugin.tools) == 1
    assert plugin.tools[0].name == "dummy.tool"


def test_parse_build_request_rejects_invalid_types() -> None:
    from thomas.plugins.p105_plugin_registry_core_model import InvalidInputError, parse_build_request

    with pytest.raises(InvalidInputError) as exc:
        parse_build_request({"include_tools": "yes"})

    assert exc.value.code == "INVALID_INPUT"


def test_parse_build_request_rejects_unknown_key() -> None:
    from thomas.plugins.p105_plugin_registry_core_model import InvalidInputError, parse_build_request

    with pytest.raises(InvalidInputError):
        parse_build_request({"nope": 123})


def test_build_plugin_registry_core_model_collects_import_errors() -> None:
    from thomas.plugins.p105_plugin_registry_core_model import (
        BuildPluginRegistryRequest,
        build_plugin_registry_core_model,
    )

    model = build_plugin_registry_core_model(
        BuildPluginRegistryRequest(plugin_modules=["does.not.exist"], include_failed=True, on_error="collect")
    )

    assert len(model.plugins) == 1
    plugin = model.plugins[0]
    assert plugin.load_error is not None
    assert plugin.load_error.code == "PLUGIN_IMPORT_FAILED"


def test_tool_envelope_returns_error_payload() -> None:
    from thomas.plugins.p105_plugin_registry_core_model import plugins_registry_model

    resp = plugins_registry_model({"include_tools": "yes"})  # invalid
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_INPUT"


def test_cli_registry_model_json_output(runner: CliRunner) -> None:
    module_name = "thomas_test_plugins.dummy_cli"
    _install_dummy_plugin(module_name)

    from thomas.cli.commands.plugins import p105_plugin_registry_core_model as cmd_mod

    result = runner.invoke(
        cmd_mod.app,
        ["registry-model", "--json", "--plugin", module_name],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["result"]["schema_version"]

    plugins = payload["result"]["plugins"]
    assert isinstance(plugins, list)
    assert any(p.get("module") == module_name for p in plugins)
