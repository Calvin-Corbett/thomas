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
    assert (pkg_dir / "plugin.json").exists()
    assert (pkg_dir / "manifest.json").exists()
    assert (pkg_dir / "thomas_plugin.json").exists()
    assert result.skill_file is not None
    assert Path(result.skill_file).exists()
    assert result.manifest_file is not None
    assert Path(result.manifest_file).exists()
    assert result.validation_ok is True
    assert result.files_created


def test_bootstrap_plugin_package_normalizes_name(tmp_path: Path) -> None:
    result = bootstrap_plugin_package(PluginBootstrapRequest(plugin_name="bad name", destination_dir=tmp_path))
    assert Path(result.package_dir).name == "bad_name"


def test_bootstrap_plugin_package_invalid_name(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError):
        bootstrap_plugin_package(PluginBootstrapRequest(plugin_name="1-invalid", destination_dir=tmp_path))


def test_bootstrap_plugin_package_exists_without_overwrite(tmp_path: Path) -> None:
    (tmp_path / "my_plugin").mkdir()
    with pytest.raises(AlreadyExistsError):
        bootstrap_plugin_package(
            PluginBootstrapRequest(plugin_name="my_plugin", destination_dir=tmp_path, overwrite=False)
        )


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
    res = runner.invoke(
        plugins_app,
        [
            "bootstrap",
            "my_plugin",
            "--dest",
            str(tmp_path),
            "--json",
            "--skill-intent",
            "runtime",
            "--skill-tool",
            "thomas.tools.list",
            "--skill-example",
            "bootstrap --help",
        ],
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["result"]["plugin_name"] == "my_plugin"
    assert payload["result"]["skill_file"] is not None
    assert Path(payload["result"]["skill_file"]).exists()
    assert payload["result"]["manifest_file"] is not None
    assert Path(payload["result"]["manifest_file"]).exists()


def test_bootstrap_plugin_package_manifest_contents(tmp_path: Path) -> None:
    result = bootstrap_plugin_package(PluginBootstrapRequest(plugin_name="my_plugin", destination_dir=tmp_path))

    plugin_json_path = Path(result.manifest_file) if result.manifest_file else None
    assert plugin_json_path is not None
    manifest = json.loads(plugin_json_path.read_text(encoding="utf-8"))
    assert manifest["name"] == "my_plugin"
    assert manifest["version"] == "0.1.0"
    assert manifest["entrypoint"] == "my_plugin.plugin:register"
    assert manifest["runtime"] == "python"
    assert manifest["capabilities"] == []


def test_bootstrap_plugin_package_skip_manifest(tmp_path: Path) -> None:
    result = bootstrap_plugin_package(
        PluginBootstrapRequest(plugin_name="my_plugin", destination_dir=tmp_path, create_manifest=False)
    )
    pkg_dir = Path(result.package_dir)
    assert not (pkg_dir / "plugin.json").exists()
    assert result.manifest_file is None


def test_bootstrap_plugin_package_install_after_bootstrap(tmp_path: Path) -> None:
    install_root = tmp_path / "plugins"
    result = bootstrap_plugin_package(
        PluginBootstrapRequest(
            plugin_name="my_plugin",
            destination_dir=tmp_path,
            install_after_bootstrap=True,
            install_root=install_root,
        )
    )

    assert result.installed_plugin == "my_plugin"
    assert result.install_root == str(install_root)
    assert result.installed_path is not None
    installed_dir = Path(result.installed_path)
    assert installed_dir.exists()
    assert installed_dir == install_root / "my_plugin"
    assert (installed_dir / "plugin.py").exists()
    assert result.installation_result_path is not None
    assert Path(result.installation_result_path).exists()


def test_cli_bootstrap_plugin_package_skip_skill(tmp_path: Path) -> None:
    # Import existing plugins CLI group and ensure command is registered.
    from thomas.cli.commands.plugins import app as plugins_app

    try:
        from thomas.cli.commands.plugins.p097_plugin_package_bootstrap import register as register_p097

        register_p097(plugins_app)
    except Exception:
        # If already registered or plugin app structure differs, proceed.
        pass

    runner = CliRunner()
    res = runner.invoke(
        plugins_app, ["bootstrap", "no_skill_plugin", "--dest", str(tmp_path), "--json", "--skip-skill"]
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["result"]["skill_file"] is None


def test_cli_bootstrap_plugin_package_skip_manifest(tmp_path: Path) -> None:
    # Import existing plugins CLI group and ensure command is registered.
    from thomas.cli.commands.plugins import app as plugins_app

    try:
        from thomas.cli.commands.plugins.p097_plugin_package_bootstrap import register as register_p097

        register_p097(plugins_app)
    except Exception:
        # If already registered or plugin app structure differs, proceed.
        pass

    runner = CliRunner()
    res = runner.invoke(
        plugins_app, ["bootstrap", "manifestless", "--dest", str(tmp_path), "--json", "--skip-manifest"]
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["result"]["manifest_file"] is None
    assert not (tmp_path / "manifestless" / "plugin.json").exists()


def test_cli_bootstrap_plugin_package_install(tmp_path: Path) -> None:
    # Import existing plugins CLI group and ensure command is registered.
    from thomas.cli.commands.plugins import app as plugins_app

    try:
        from thomas.cli.commands.plugins.p097_plugin_package_bootstrap import register as register_p097

        register_p097(plugins_app)
    except Exception:
        # If already registered or plugin app structure differs, proceed.
        pass

    install_root = tmp_path / "plugins"
    runner = CliRunner()
    res = runner.invoke(
        plugins_app,
        [
            "bootstrap",
            "cli_installed_plugin",
            "--dest",
            str(tmp_path),
            "--json",
            "--install",
            "--install-root",
            str(install_root),
        ],
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["result"]["installed_path"] is not None
    assert Path(payload["result"]["installed_path"]) == install_root / "cli_installed_plugin"
