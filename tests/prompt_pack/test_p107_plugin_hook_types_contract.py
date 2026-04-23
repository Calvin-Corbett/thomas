from __future__ import annotations

import json
import sys
import types

import pytest
from typer.testing import CliRunner

from thomas.plugins.p107_plugin_hook_types_contract import (
    HookTypesContractError,
    HookTypesContractErrorCode,
    HookTypesContractRequest,
    build_hook_types_contract,
)
from thomas.cli.commands.plugins.p107_plugin_hook_types_contract import app


class DummyPluginBase:
    """A tiny stand-in for Thomas' real plugin base class."""

    HOOKS = ["on_start", "before_tool", "after_tool"]

    def on_start(self, context: dict) -> None:
        """Called when the agent starts."""
        return None

    async def before_tool(self, name: str, args: dict, *, timeout: float = 1.0) -> dict:
        """Called before a tool runs."""
        return args

    def after_tool(self, name: str, result: object) -> object:
        """Called after a tool runs."""
        return result


def _install_dummy_module() -> str:
    mod = types.ModuleType("_p107_dummy_mod")
    mod.DummyPluginBase = DummyPluginBase
    sys.modules[mod.__name__] = mod
    return f"{mod.__name__}.DummyPluginBase"


def test_contract_build_success_from_explicit_class_path():
    path = _install_dummy_module()
    req = HookTypesContractRequest(plugin_base=path, include_inherited=True, include_private=False)
    contract = build_hook_types_contract(req)

    assert contract.plugin_base == path
    names = [h.name for h in contract.hooks]
    assert names == sorted(DummyPluginBase.HOOKS)

    before = next(h for h in contract.hooks if h.name == "before_tool")
    assert before.is_async is True
    assert any(p.name == "timeout" and p.has_default for p in before.parameters)


def test_contract_invalid_plugin_base_path_is_deterministic():
    with pytest.raises(HookTypesContractError) as ei:
        build_hook_types_contract({"plugin_base": "not_a_dotted_path"})
    assert ei.value.code == HookTypesContractErrorCode.INVALID_INPUT


def test_cli_json_success():
    path = _install_dummy_module()
    runner = CliRunner()
    result = runner.invoke(app, ["--plugin-base", path, "--json"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["contract"]["plugin_base"] == path
    assert isinstance(payload["contract"]["hooks"], list)


def test_cli_missing_config_is_deterministic_json_error():
    runner = CliRunner()
    result = runner.invoke(app, ["--config", "does-not-exist.toml", "--json"])
    assert result.exit_code == 2

    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == HookTypesContractErrorCode.MISSING_CONFIG.value


def test_cli_schema_output_is_machine_readable():
    runner = CliRunner()
    result = runner.invoke(app, ["--schema"])
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["result"]["type"] == "object"
    assert "hooks" in payload["result"]["properties"]
