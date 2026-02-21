from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.plugins.p097_plugin_package_bootstrap import (
    AlreadyExistsError,
    InvalidInputError,
    PluginBootstrapRequest,
    bootstrap_plugin_package,
)


def test_bootstrap_plugin_package_creates_files(tmp_path: Path) -> None:
    result = bootstrap_plugin_package(PluginBootstrapRequest(plugin_name="my_plugin", destination_dir=tmp_path))

    pkg_dir = Path(result.package_dir)
    assert pkg_dir.exists()
    assert (pkg_dir / "__init__.py").exists()
    assert (pkg_dir / "plugin.py").exists()
    assert (pkg_dir / "pyproject.toml").exists()
    assert (pkg_dir / "README.md").exists()
    assert result.files_created


def test_bootstrap_plugin_package_invalid_name(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError):
        bootstrap_plugin_package(PluginBootstrapRequest(plugin_name="bad-name", destination_dir=tmp_path))


def test_bootstrap_plugin_package_exists_without_overwrite(tmp_path: Path) -> None:
    (tmp_path / "my_plugin").mkdir()
    with pytest.raises(AlreadyExistsError):
        bootstrap_plugin_package(PluginBootstrapRequest(plugin_name="my_plugin", destination_dir=tmp_path, overwrite=False))


def test_cli_bootstrap_plugin_package_json_success(tmp_path: Path) -> None:
    # Import existing plugins CLI group and ensure command is registered.
    from thomas.cli.commands.plugins import app as plugins_app

    try:
        from thomas.cli.commands.plugins.p097_plugin_package_bootstrap import register as register_p097

        register_p097(plugins_app)
    except Exception:
        # If already registered or plugin app structure differs, proceed.
        pass

    runner = CliRunner()
    res = runner.invoke(plugins_app, ["bootstrap", "my_plugin", "--dest", str(tmp_path), "--json"])
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["result"]["plugin_name"] == "my_plugin"
