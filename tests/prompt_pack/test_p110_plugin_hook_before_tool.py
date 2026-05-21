import json

import pytest
import typer
from typer.testing import CliRunner

from thomas.cli.commands.plugins import p110_plugin_hook_before_tool as cmd
from thomas.plugins.p110_plugin_hook_before_tool import (
    BeforeToolHookConfig,
    ExternalHookFailure,
    HookConfigError,
    HookInputError,
    P110BeforeToolHookPlugin,
    ToolBlockedError,
    ToolCall,
    apply_before_tool_hook,
    run_tool_with_before_tool_hook,
)


def _build_app() -> typer.Typer:
    # Emulate the real CLI shape: a root app with a `plugins` sub-app.
    root = typer.Typer()
    plugins = typer.Typer()
    cmd.register(plugins)
    root.add_typer(plugins, name="plugins")
    return root


def test_plugin_allows_modify_of_text_arg() -> None:
    plugin = P110BeforeToolHookPlugin(
        config=BeforeToolHookConfig(mode="modify", prefix="[TEST] ", blocked_substrings=())
    )
    call = ToolCall(name="demo.echo", args={"text": "hi"})

    decision, updated = apply_before_tool_hook(plugin, call)
    assert decision.action == "modify"
    assert updated.args["text"] == "[TEST] hi"


def test_plugin_blocks_on_dangerous_pattern() -> None:
    plugin = P110BeforeToolHookPlugin(config=BeforeToolHookConfig(mode="allow", blocked_substrings=("rm -rf /",)))
    call = ToolCall(name="demo.shell", args={"command": "rm -rf /"})

    decision, _ = apply_before_tool_hook(plugin, call)
    assert decision.action == "block"

    def _fake_tool(**kwargs):  # pragma: no cover
        return "should not run"

    with pytest.raises(ToolBlockedError) as exc:
        run_tool_with_before_tool_hook(plugin, _fake_tool, call)

    assert exc.value.code == "tool_blocked"


def test_invalid_tool_call_rejected_deterministically() -> None:
    with pytest.raises(HookInputError) as exc:
        ToolCall(name="", args={})
    assert exc.value.code == "invalid_tool_name"


def test_missing_config_strict_load_is_deterministic() -> None:
    with pytest.raises(HookConfigError) as exc:
        BeforeToolHookConfig.from_mapping(None, strict=True)
    assert exc.value.code == "missing_config"


def test_external_failure_is_deterministic() -> None:
    plugin = P110BeforeToolHookPlugin(config=BeforeToolHookConfig(mode="allow", simulate_external_failure=True))
    call = ToolCall(name="demo.echo", args={"text": "hi"})

    with pytest.raises(ExternalHookFailure) as exc:
        plugin.before_tool(call)
    assert exc.value.code == "external_failure"


def test_cli_json_success() -> None:
    runner = CliRunner()
    result = runner.invoke(
        _build_app(),
        ["plugins", "p110-plugin-hook-before-tool", "--json"],
    )
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["tool"]["name"] == "demo.echo"
    assert payload["data"]["hook"]["action"] in ("modify", "allow")


def test_cli_json_invalid_mode_failure() -> None:
    runner = CliRunner()
    result = runner.invoke(
        _build_app(),
        ["plugins", "p110-plugin-hook-before-tool", "--mode", "nope", "--json"],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_mode"


def test_cli_json_external_failure() -> None:
    runner = CliRunner()
    result = runner.invoke(
        _build_app(),
        ["plugins", "p110-plugin-hook-before-tool", "--simulate-external-failure", "--json"],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "external_failure"


def test_cli_json_schema() -> None:
    runner = CliRunner()
    result = runner.invoke(
        _build_app(),
        ["plugins", "p110-plugin-hook-before-tool", "--json-schema"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["type"] == "object"
    assert "ok" in payload["properties"]
