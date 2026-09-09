from __future__ import annotations

import json

import pytest

from thomas.cli.commands.plugins.p121_plugin_list_command_runtime_backed import run as run_cli
from thomas.plugins.p121_plugin_list_command_runtime_backed import (
    PluginListError,
    PluginListRequest,
    list_plugins_runtime_backed,
)


def _write_json(path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def test_runtime_list_supports_dict_sections_and_manifests(tmp_path):
    config_path = tmp_path / "thomas.json"
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True)

    alpha_dir = plugins_dir / "alpha"
    alpha_dir.mkdir()
    _write_json(alpha_dir / "package.json", {"name": "Alpha Plugin", "version": "2.3.4"})

    _write_json(
        config_path,
        {
            "plugins": {
                "entries": {"alpha": {"enabled": True}, "beta": {"enabled": False}},
                "installs": {"alpha": {"source": "local", "spec": "./alpha", "version": "1.0.0"}},
            }
        },
    )

    result = list_plugins_runtime_backed(PluginListRequest(config_path=config_path, plugins_dir=plugins_dir))
    assert [p.plugin_id for p in result.plugins] == ["alpha", "beta"]

    alpha = result.plugins[0]
    assert alpha.enabled is True
    assert alpha.installed is True
    assert alpha.status == "ok"
    assert alpha.name == "Alpha Plugin"
    assert alpha.version == "2.3.4"  # manifest wins

    beta = result.plugins[1]
    assert beta.enabled is False
    assert beta.installed is False
    assert beta.status == "missing"


def test_runtime_list_supports_list_sections(tmp_path):
    config_path = tmp_path / "thomas.json"
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True)

    (plugins_dir / "gamma").mkdir()
    _write_json(plugins_dir / "gamma" / "plugin.json", {"displayName": "Gamma", "version": "9.9.9"})

    _write_json(
        config_path,
        {
            "plugins": {
                "entries": [{"id": "gamma", "enabled": True}, {"id": "delta", "enabled": True}],
                "installs": [{"id": "gamma", "source": "local"}],
            }
        },
    )

    result = list_plugins_runtime_backed(PluginListRequest(config_path=config_path, plugins_dir=plugins_dir))
    assert [p.plugin_id for p in result.plugins] == ["delta", "gamma"]  # sorted
    delta = next(p for p in result.plugins if p.plugin_id == "delta")
    assert delta.status == "missing"
    gamma = next(p for p in result.plugins if p.plugin_id == "gamma")
    assert gamma.status == "ok"
    assert gamma.name == "Gamma"
    assert gamma.version == "9.9.9"


def test_manifest_parse_error_is_captured_per_plugin(tmp_path):
    config_path = tmp_path / "thomas.json"
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True)

    bad_dir = plugins_dir / "bad"
    bad_dir.mkdir()
    (bad_dir / "package.json").write_text("{not json}", encoding="utf-8")

    _write_json(config_path, {"plugins": {"entries": {"bad": {"enabled": True}}, "installs": {}}})

    result = list_plugins_runtime_backed(PluginListRequest(config_path=config_path, plugins_dir=plugins_dir))
    item = result.plugins[0]
    assert item.plugin_id == "bad"
    assert item.installed is True
    assert item.status == "error"
    assert item.error is not None
    assert "manifest_error" in item.error


def test_missing_config_raises_deterministic_error(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(PluginListError) as exc:
        list_plugins_runtime_backed(PluginListRequest(config_path=missing))
    assert exc.value.code == "CONFIG_MISSING"


def test_cli_json_and_schema(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    plugins_dir = home / "plugins"
    plugins_dir.mkdir()

    (plugins_dir / "alpha").mkdir()
    _write_json(plugins_dir / "alpha" / "package.json", {"name": "alpha", "version": "0.1.0"})

    config_path = home / "thomas.json"
    _write_json(config_path, {"plugins": {"entries": {"alpha": {"enabled": True}}, "installs": {}}})

    monkeypatch.setenv("THOMAS_HOME", str(home))
    monkeypatch.setenv("THOMAS_CONFIG_PATH", str(config_path))

    code = run_cli(["--schema"])
    assert code == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["type"] == "object"

    code = run_cli(["--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["plugins"][0]["id"] == "alpha"


def test_cli_only_enabled_filters(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    plugins_dir = home / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "a").mkdir()
    _write_json(plugins_dir / "a" / "plugin.json", {"name": "a", "version": "1.0.0"})

    config_path = home / "thomas.json"
    _write_json(
        config_path,
        {"plugins": {"entries": {"a": {"enabled": True}, "b": {"enabled": False}}, "installs": {}}},
    )

    monkeypatch.setenv("THOMAS_HOME", str(home))
    monkeypatch.setenv("THOMAS_CONFIG_PATH", str(config_path))

    code = run_cli(["--json", "--only-enabled"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    ids = [p["id"] for p in payload["plugins"]]
    assert ids == ["a"]


def test_cli_failure_json_on_missing_config(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("THOMAS_HOME", str(home))
    monkeypatch.setenv("THOMAS_CONFIG_PATH", str(home / "nope.json"))

    code = run_cli(["--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CONFIG_MISSING"
