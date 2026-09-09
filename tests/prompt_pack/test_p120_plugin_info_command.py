import json

import pytest
import typer
from typer.testing import CliRunner

from thomas.cli.commands.plugins import p120_plugin_info_command as cli_mod
from thomas.plugins.p120_plugin_info_command import (
    ERR_EXTERNAL_FAILURE,
    ERR_INVALID_INPUT,
    ERR_MISSING_CONFIG,
    ERR_NOT_FOUND,
    PluginInfoCommandError,
    PluginInfoCommandInput,
    run_plugin_info_command,
)


def test_plugin_info_success_from_stubbed_report():
    def stub_report():
        return {
            "plugins": [
                {
                    "id": "demo",
                    "name": "Demo Plugin",
                    "status": "loaded",
                    "toolNames": ["tool.a", "tool.b"],
                }
            ]
        }

    out = run_plugin_info_command(
        PluginInfoCommandInput(plugin_id="demo"),
        status_report_provider=stub_report,
    )
    assert out.plugin["id"] == "demo"
    assert out.plugin["status"] == "loaded"
    assert out.plugin["toolNames"] == ["tool.a", "tool.b"]


def test_plugin_info_success_by_name_and_case_insensitive():
    def stub_report():
        return {"plugins": [{"id": "demo", "name": "Demo Plugin"}]}

    out = run_plugin_info_command(
        PluginInfoCommandInput(plugin_id="Demo Plugin"),
        status_report_provider=stub_report,
    )
    assert out.plugin["id"] == "demo"

    out2 = run_plugin_info_command(
        PluginInfoCommandInput(plugin_id="DEMO"),
        status_report_provider=stub_report,
    )
    assert out2.plugin["id"] == "demo"


def test_plugin_info_not_found_is_deterministic():
    def stub_report():
        return {"plugins": [{"id": "a", "name": "a"}]}

    with pytest.raises(PluginInfoCommandError) as exc_info:
        run_plugin_info_command(
            PluginInfoCommandInput(plugin_id="missing"),
            status_report_provider=stub_report,
        )

    err = exc_info.value
    assert err.code == ERR_NOT_FOUND
    assert err.message == "Plugin not found: missing"


def test_plugin_info_invalid_input_is_deterministic():
    def stub_report():
        return {"plugins": []}

    with pytest.raises(PluginInfoCommandError) as exc_info:
        run_plugin_info_command(
            PluginInfoCommandInput(plugin_id="   "),
            status_report_provider=stub_report,
        )

    err = exc_info.value
    assert err.code == ERR_INVALID_INPUT
    assert err.message == "Plugin id is required."


def test_plugin_info_missing_config_is_deterministic():
    def stub_report():
        raise FileNotFoundError("no config")

    with pytest.raises(PluginInfoCommandError) as exc_info:
        run_plugin_info_command(
            PluginInfoCommandInput(plugin_id="demo"),
            status_report_provider=stub_report,
        )

    err = exc_info.value
    assert err.code == ERR_MISSING_CONFIG
    assert "Missing Thomas configuration" in err.message


def test_plugin_info_external_failure_is_deterministic():
    def stub_report():
        raise RuntimeError("boom")

    with pytest.raises(PluginInfoCommandError) as exc_info:
        run_plugin_info_command(
            PluginInfoCommandInput(plugin_id="demo"),
            status_report_provider=stub_report,
        )

    err = exc_info.value
    assert err.code == ERR_EXTERNAL_FAILURE
    assert err.message == "Failed to build plugin status report."


def test_cli_json_success(monkeypatch):
    runner = CliRunner()
    app = typer.Typer()
    cli_mod.register(app)

    def stub_report():
        return {"plugins": [{"id": "demo", "name": "demo", "status": "loaded"}]}

    import thomas.plugins.p120_plugin_info_command as core_mod

    monkeypatch.setattr(core_mod, "_build_plugin_status_report", lambda: stub_report())

    res = runner.invoke(app, ["info", "demo", "--json"])
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["id"] == "demo"
    assert payload["status"] == "loaded"


def test_cli_error_goes_to_stderr(monkeypatch):
    runner = CliRunner()
    app = typer.Typer()
    cli_mod.register(app)

    def stub_report():
        return {"plugins": [{"id": "demo", "name": "demo"}]}

    import thomas.plugins.p120_plugin_info_command as core_mod

    monkeypatch.setattr(core_mod, "_build_plugin_status_report", lambda: stub_report())

    res = runner.invoke(app, ["info", "missing", "--json"])
    assert res.exit_code == 1
    assert res.output.strip() == "Plugin not found: missing"
