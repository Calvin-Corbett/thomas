"""
CLI command: plugins install-from-local-path

Installs a plugin from a local filesystem directory.

This command supports:
- Human-readable output (default)
- Machine-readable output (--json) for automation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import click

from thomas.plugins.p102_plugin_install_from_local_path import (
    PluginInstallFromLocalPathError,
    run as run_install_from_local_path,
)

COMMAND_NAME = "install-from-local-path"


def _payload(
    *,
    source_path: Path,
    plugin_name: Optional[str],
    install_root: Optional[Path],
    overwrite: bool,
) -> dict[str, Any]:
    p: dict[str, Any] = {"source_path": str(source_path)}
    if plugin_name:
        p["plugin_name"] = plugin_name
    if install_root is not None:
        p["install_root"] = str(install_root)
    if overwrite:
        p["overwrite"] = True
    return p


def _echo_json(echo: Any, payload: Any) -> None:
    echo(json.dumps(payload, sort_keys=True))


def _human_success_message(result: dict[str, Any]) -> str:
    return f"Installed plugin '{result['plugin_name']}' to {result['installed_path']}"


def _run(
    *,
    source_path: Path,
    plugin_name: Optional[str],
    install_root: Optional[Path],
    overwrite: bool,
    json_output: bool,
    echo: Any,
) -> None:
    payload = _payload(
        source_path=source_path,
        plugin_name=plugin_name,
        install_root=install_root,
        overwrite=overwrite,
    )
    result = run_install_from_local_path(payload)

    if json_output:
        _echo_json(echo, result)
        if not result.get("ok", False):
            raise click.exceptions.Exit(1)
        return

    if result.get("ok", False):
        echo(_human_success_message(result))
        return

    err = result.get("error") or {}
    code = err.get("code", "error")
    msg = err.get("message", "Unknown error")
    raise click.ClickException(f"{code}: {msg}")


@click.command(name=COMMAND_NAME, help="Install a plugin from a local directory path.")
@click.argument("source_path", type=click.Path(exists=False, file_okay=False, path_type=Path))
@click.option("--name", "plugin_name", type=str, default=None, help="Override the plugin name.")
@click.option(
    "--install-root",
    "install_root",
    type=click.Path(exists=False, file_okay=False, path_type=Path),
    default=None,
    help="Override the install root directory.",
)
@click.option("--overwrite", is_flag=True, default=False, help="Overwrite if the plugin already exists.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit machine-readable JSON output.")
def command(
    source_path: Path,
    plugin_name: Optional[str],
    install_root: Optional[Path],
    overwrite: bool,
    json_output: bool,
) -> None:
    try:
        _run(
            source_path=source_path,
            plugin_name=plugin_name,
            install_root=install_root,
            overwrite=overwrite,
            json_output=json_output,
            echo=click.echo,
        )
    except PluginInstallFromLocalPathError as e:
        # This should rarely happen because the underlying tool returns structured errors,
        # but keep it deterministic if it does.
        if json_output:
            _echo_json(click.echo, e.to_dict())
            raise click.exceptions.Exit(1)
        raise click.ClickException(f"{e.code}: {e}") from e


# Compatibility aliases for various CLI wiring patterns.
COMMAND = command


def get_command() -> click.Command:
    return command


def register(app: Any) -> None:
    """
    Best-effort registration hook.

    Supports:
    - Click Group-like objects with `.add_command`
    - Typer apps (registered via a wrapper command)
    """
    if hasattr(app, "add_command"):
        app.add_command(command)  # type: ignore[attr-defined]
        return

    try:
        import typer  # type: ignore

        if isinstance(app, typer.Typer):

            @app.command(COMMAND_NAME)
            def _typer_cmd(
                source_path: Path,
                name: Optional[str] = typer.Option(None, "--name"),
                install_root: Optional[Path] = typer.Option(None, "--install-root"),
                overwrite: bool = typer.Option(False, "--overwrite"),
                json_output: bool = typer.Option(False, "--json"),
            ) -> None:
                _run(
                    source_path=source_path,
                    plugin_name=name,
                    install_root=install_root,
                    overwrite=overwrite,
                    json_output=json_output,
                    echo=typer.echo,
                )

            return
    except Exception:
        pass

    raise RuntimeError("Unsupported CLI app type for command registration.")


__all__ = ["COMMAND_NAME", "command", "COMMAND", "get_command", "register"]
