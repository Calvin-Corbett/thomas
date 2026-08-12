from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.cli.commands.plugins.p103_plugin_uninstall_cleanup import app as cli_app
from thomas.plugins.p103_plugin_uninstall_cleanup import (
    ManagedPluginUninstallRequest,
    PluginUninstallCleanupError,
    PluginUninstallCleanupRequest,
    run_plugin_uninstall_cleanup,
    uninstall_plugin_from_install_root,
)


def _write_config(state_dir: Path) -> Path:
    config_path = state_dir / "thomas.json"
    config_path.write_text("{}", encoding="utf-8")
    return config_path


def _make_plugin_dir(state_dir: Path, plugin_id: str) -> Path:
    plugin_dir = state_dir / "extensions" / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "dummy.txt").write_text("hello", encoding="utf-8")
    return plugin_dir


def test_cleanup_removes_plugin_directory(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = _write_config(state_dir)

    plugin_dir = _make_plugin_dir(state_dir, "my-plugin")
    assert plugin_dir.exists()

    req = PluginUninstallCleanupRequest(plugin_id="my-plugin", config_path=config_path)
    res = run_plugin_uninstall_cleanup(req)

    assert res.status == "removed"
    assert not plugin_dir.exists()
    assert str(plugin_dir) in [str(p) for p in res.removed]


def test_cleanup_not_found_is_ok(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = _write_config(state_dir)

    req = PluginUninstallCleanupRequest(plugin_id="missing-plugin", config_path=config_path)
    res = run_plugin_uninstall_cleanup(req)

    assert res.status == "not_found"
    assert res.removed == ()


def test_invalid_plugin_id_rejected(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = _write_config(state_dir)

    req = PluginUninstallCleanupRequest(plugin_id="../evil", config_path=config_path)
    with pytest.raises(PluginUninstallCleanupError) as excinfo:
        run_plugin_uninstall_cleanup(req)

    assert excinfo.value.code == "invalid_input"


def test_cleanup_missing_config_is_deterministic_error(tmp_path: Path) -> None:
    missing_cfg = tmp_path / "does-not-exist.json"

    req = PluginUninstallCleanupRequest(plugin_id="my-plugin", config_path=missing_cfg)
    with pytest.raises(PluginUninstallCleanupError) as excinfo:
        run_plugin_uninstall_cleanup(req)

    err = excinfo.value
    assert err.code == "missing_config"
    assert err.details.get("config_path") == str(missing_cfg)


def test_cli_json_success_and_failure(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = _write_config(state_dir)
    plugin_dir = _make_plugin_dir(state_dir, "my-plugin")

    runner = CliRunner()

    ok = runner.invoke(cli_app, ["my-plugin", "--config-path", str(config_path), "--json"])
    assert ok.exit_code == 0
    payload = json.loads(ok.stdout.strip())
    assert payload["ok"] is True
    assert payload["result"]["status"] == "removed"
    assert str(plugin_dir) in payload["result"]["removed"]

    # not_found is still ok
    nf = runner.invoke(cli_app, ["missing-plugin", "--config-path", str(config_path), "--json"])
    assert nf.exit_code == 0
    payload_nf = json.loads(nf.stdout.strip())
    assert payload_nf["ok"] is True
    assert payload_nf["result"]["status"] == "not_found"

    bad_cfg = tmp_path / "missing.json"
    fail = runner.invoke(cli_app, ["my-plugin", "--config-path", str(bad_cfg), "--json"])
    assert fail.exit_code == 2
    payload2 = json.loads(fail.stdout.strip())
    assert payload2["ok"] is False
    assert payload2["error"]["code"] == "missing_config"


def test_managed_uninstall_removes_payload_and_runtime_state_atomically(tmp_path: Path) -> None:
    install_root = tmp_path / "plugins"
    plugin_dir = install_root / "launch_guide"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "knowledge.md").write_text("BLUE-CEDAR-936", encoding="utf-8")
    manifest_path = install_root / "installed_plugins.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugins": {
                    "launch_guide": {
                        "installed_path": str(plugin_dir.resolve()),
                        "source_path": str((tmp_path / "source").resolve()),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = uninstall_plugin_from_install_root(
        ManagedPluginUninstallRequest(plugin_id="launch_guide", install_root=install_root)
    )

    assert result.status == "removed"
    assert result.manifest_updated is True
    assert not plugin_dir.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["plugins"] == {}
    again = uninstall_plugin_from_install_root(
        ManagedPluginUninstallRequest(plugin_id="launch_guide", install_root=install_root)
    )
    assert again.status == "not_found"


def test_managed_uninstall_rejects_manifest_path_mismatch_without_deleting(tmp_path: Path) -> None:
    install_root = tmp_path / "plugins"
    plugin_dir = install_root / "launch_guide"
    plugin_dir.mkdir(parents=True)
    (install_root / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 1,
                "plugins": {"launch_guide": {"installed_path": str((tmp_path / "outside").resolve())}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PluginUninstallCleanupError) as exc:
        uninstall_plugin_from_install_root(
            ManagedPluginUninstallRequest(plugin_id="launch_guide", install_root=install_root)
        )
    assert exc.value.code == "bad_manifest"
    assert plugin_dir.exists()
