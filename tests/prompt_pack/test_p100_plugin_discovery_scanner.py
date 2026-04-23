from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.plugins.p100_plugin_discovery_scanner import (
    PluginDiscoveryScanRequest,
    PluginDiscoveryScannerError,
    scan_plugins,
)
from thomas.cli.commands.plugins import p100_plugin_discovery_scanner as cli_mod


def test_scan_filesystem_success(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "hello_plugin.py"
    plugin_file.write_text(
        "\n".join(
            [
                '"""A tiny test plugin."""',
                'PLUGIN_NAME = "hello"',
                'PLUGIN_VERSION = "1.2.3"',
                'PLUGIN_DESCRIPTION = "Hello plugin"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    res = scan_plugins(
        PluginDiscoveryScanRequest(
            search_paths=[str(plugin_dir)],
            include_entry_points=False,
            import_plugins=False,
        )
    )

    assert res.scanned_paths
    assert len(res.plugins) == 1
    p = res.plugins[0]
    assert p.name == "hello"
    assert p.source == "filesystem"
    assert p.module == "hello_plugin"
    assert p.file_path and p.file_path.endswith("hello_plugin.py")
    assert p.version == "1.2.3"
    assert p.description == "Hello plugin"
    assert p.import_checked is False
    assert p.importable is None
    assert p.issues == []


def test_scan_invalid_path_is_deterministic(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    with pytest.raises(PluginDiscoveryScannerError) as exc:
        scan_plugins(
            PluginDiscoveryScanRequest(
                search_paths=[str(missing)],
                include_entry_points=False,
            )
        )
    assert exc.value.code == "path_not_found"


def test_scan_missing_config_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(PluginDiscoveryScannerError) as exc:
        scan_plugins(PluginDiscoveryScanRequest(search_paths=None, include_entry_points=False))

    assert exc.value.code == "missing_config"


def test_cli_json_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "ok.py").write_text('PLUGIN_NAME="ok"\n', encoding="utf-8")

    exit_code = cli_mod.run(["--path", str(plugin_dir), "--no-entry-points", "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0

    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["result"]["plugins"][0]["name"] == "ok"


def test_cli_json_strict_failure_on_import_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "bad.py").write_text("import does_not_exist\n", encoding="utf-8")

    exit_code = cli_mod.run(["--path", str(plugin_dir), "--no-entry-points", "--import", "--strict", "--json"])
    captured = capsys.readouterr()

    assert exit_code == 3
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "plugin_load_failure"
    assert payload["error"]["details"]["plugins_with_issues"]
