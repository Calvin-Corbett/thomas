from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from thomas.cli.commands.plugins.p119_plugin_doctor_command import run_cli
from thomas.plugins.p119_plugin_doctor_command import (
    InvalidPluginDoctorInput,
    PluginConfigNotFound,
    PluginDoctorRequest,
    run_plugin_doctor,
)


def test_plugin_doctor_success_all_pass(monkeypatch):
    import thomas.plugins.p119_plugin_doctor_command as mod

    monkeypatch.setattr(
        mod,
        "_discover_plugin_module_names",
        lambda *, include_hidden: (["thomas.plugins.alpha", "thomas.plugins.beta"], None),
    )

    def fake_import(name: str):
        # Core modules and plugins always import ok in this test.
        if name.startswith("thomas.plugins."):
            m = types.SimpleNamespace()

            def register(registry):
                registry.register_tool(f"{name}.tool", lambda: None, description="x")

            m.register = register
            return m, None, {}

        return types.SimpleNamespace(), None, {}

    monkeypatch.setattr(mod, "_try_import_module", fake_import)

    report = run_plugin_doctor(PluginDoctorRequest())
    assert report.ok is True
    assert report.inspected == ["thomas.plugins.alpha", "thomas.plugins.beta"]
    assert all(c.status == "pass" for c in report.checks)

    # Must be JSON serializable for automation.
    json.dumps(report.to_dict())


def test_plugin_doctor_failure_when_plugin_import_fails(monkeypatch):
    import thomas.plugins.p119_plugin_doctor_command as mod

    monkeypatch.setattr(
        mod,
        "_discover_plugin_module_names",
        lambda *, include_hidden: (["thomas.plugins.ok", "thomas.plugins.bad"], None),
    )

    def fake_import(name: str):
        if name == "thomas.plugins.bad":
            return None, "ImportError: boom", {"exception_type": "ImportError", "exception_message": "boom"}
        if name.startswith("thomas.plugins."):
            m = types.SimpleNamespace()

            def register(registry):
                registry.register_tool(f"{name}.tool", lambda: None, description="x")

            m.register = register
            return m, None, {}

        return types.SimpleNamespace(), None, {}

    monkeypatch.setattr(mod, "_try_import_module", fake_import)

    report = run_plugin_doctor(PluginDoctorRequest())
    assert report.ok is False
    assert report.inspected == ["thomas.plugins.ok", "thomas.plugins.bad"]
    assert any(c.status == "fail" and c.id == "plugin-import:thomas.plugins.bad" for c in report.checks)

    exit_code, out = run_cli(json_mode=True)
    assert exit_code == 1
    payload = json.loads(out)
    assert payload["ok"] is False
    assert any(ch["status"] == "fail" for ch in payload["checks"])


def test_plugin_doctor_invalid_input_plugin_name():
    with pytest.raises(InvalidPluginDoctorInput):
        run_plugin_doctor(PluginDoctorRequest(plugin="not valid"))  # contains space


def test_plugin_doctor_unknown_plugin_module_json_error():
    # CLI wrapper should surface deterministic INVALID_INPUT errors as JSON.
    exit_code, out = run_cli(plugin="this_plugin_module_does_not_exist_123456", json_mode=True)
    assert exit_code == 2
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_INPUT"


def test_plugin_doctor_missing_config_path(tmp_path: Path):
    missing = tmp_path / "nope.toml"
    with pytest.raises(PluginConfigNotFound):
        run_plugin_doctor(PluginDoctorRequest(config_path=str(missing)))
