from __future__ import annotations

"""P097 CLI wiring: plugin package bootstrap.

This module is designed to be imported by the existing plugins CLI group.
It exposes a `register(app)` hook and provides JSON output for automation.
"""

import json
from pathlib import Path
from typing import Any

import typer

from thomas.plugins.p097_plugin_package_bootstrap import (
    PluginBootstrapError,
    PluginBootstrapRequest,
    bootstrap_plugin_package,
)


def _emit_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def register(app: typer.Typer) -> None:
    @app.command("bootstrap")
    def bootstrap(  # noqa: WPS430 - Typer command function
        plugin_name: str = typer.Argument(..., help="Python package name for the plugin."),
        destination: Path = typer.Option(Path("."), "--dest", help="Directory to create the plugin package within."),
        description: str = typer.Option("Thomas plugin package", "--description", help="Plugin package description."),
        author: str = typer.Option("", "--author", help="Author string used in generated metadata."),
        overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing files if the package exists."),
        json_output: bool = typer.Option(False, "--json", help="Machine readable output."),
    ) -> None:
        try:
            result = bootstrap_plugin_package(
                PluginBootstrapRequest(
                    plugin_name=plugin_name,
                    destination_dir=destination,
                    description=description,
                    author=author,
                    overwrite=overwrite,
                )
            )
        except PluginBootstrapError as e:
            if json_output:
                _emit_json({"ok": False, "error": e.to_dict()})
            else:
                typer.echo(f"ERROR[{e.code}]: {e.message}", err=True)
            raise typer.Exit(code=2) from e

        if json_output:
            _emit_json({"ok": True, "result": result.to_dict()})
        else:
            typer.echo(f"Bootstrapped plugin package at: {result.package_dir}")
