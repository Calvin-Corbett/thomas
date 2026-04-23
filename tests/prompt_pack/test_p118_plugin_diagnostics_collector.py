from __future__ import annotations

import json

import pytest


def test_collect_plugin_diagnostics_success_for_self_plugin() -> None:
    from thomas.plugins.p118_plugin_diagnostics_collector import PluginDiagnosticsInput, collect_plugin_diagnostics

    report = collect_plugin_diagnostics(
        PluginDiagnosticsInput(
            plugin_names=["p118_plugin_diagnostics_collector"],
            include_tools=False,
            strict=True,
        )
    )
    assert report.ok is True
    assert any(p.name == "p118_plugin_diagnostics_collector" and p.status == "loaded" for p in report.plugins)


def test_collect_plugin_diagnostics_invalid_input_is_deterministic() -> None:
    from thomas.plugins.p118_plugin_diagnostics_collector import (
        ERROR_INVALID_INPUT,
        PluginDiagnosticsCollectorError,
        PluginDiagnosticsInput,
        collect_plugin_diagnostics,
    )

    with pytest.raises(PluginDiagnosticsCollectorError) as exc:
        collect_plugin_diagnostics(PluginDiagnosticsInput(plugin_names=["  "], include_tools=False, strict=True))
    assert exc.value.code == ERROR_INVALID_INPUT


def test_collect_plugin_diagnostics_unknown_plugin_is_deterministic() -> None:
    from thomas.plugins.p118_plugin_diagnostics_collector import (
        ERROR_UNKNOWN_PLUGIN,
        PluginDiagnosticsCollectorError,
        PluginDiagnosticsInput,
        collect_plugin_diagnostics,
    )

    with pytest.raises(PluginDiagnosticsCollectorError) as exc:
        collect_plugin_diagnostics(
            PluginDiagnosticsInput(
                plugin_names=["definitely_not_a_real_plugin"],
                include_tools=False,
                strict=True,
            )
        )

    assert exc.value.code == ERROR_UNKNOWN_PLUGIN
    assert "No matching plugins" in str(exc.value)


def test_collect_plugin_diagnostics_import_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force discovery to return a fake plugin module ref that will fail import.
    import thomas.plugins.p118_plugin_diagnostics_collector as mod

    monkeypatch.setattr(mod, "_discover_plugins", lambda: [mod._PluginModuleRef(base="bad", full="thomas.plugins.bad")])

    def _boom(name: str, *args, **kwargs):
        if name == "thomas.plugins.bad":
            raise ImportError("boom")
        return __import__(name)

    monkeypatch.setattr(mod.importlib, "import_module", _boom)

    report = mod.collect_plugin_diagnostics(mod.PluginDiagnosticsInput(plugin_names=["bad"], include_tools=False))
    assert report.ok is False
    assert report.plugins[0].status == "error"
    assert any(i.code == mod.ERROR_PLUGIN_IMPORT_FAILED for i in report.issues)


def test_cli_json_output_success() -> None:
    from typer.testing import CliRunner
    from thomas.cli.commands.plugins.p118_plugin_diagnostics_collector import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--plugin",
            "p118_plugin_diagnostics_collector",
            "--no-include-tools",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert any(p["name"] == "p118_plugin_diagnostics_collector" for p in payload.get("plugins", []))


def test_cli_json_output_unknown_plugin_failure() -> None:
    from typer.testing import CliRunner
    from thomas.cli.commands.plugins.p118_plugin_diagnostics_collector import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--plugin",
            "definitely_not_a_real_plugin",
            "--no-include-tools",
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_plugin"
