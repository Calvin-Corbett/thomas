"""
P120 - CLI wiring for `thomas plugins info`.

This file defines the CLI command surface and delegates the core behavior to:
  - thomas.plugins.p120_plugin_info_command
"""

from __future__ import annotations

import json

import typer

from thomas.plugins.p120_plugin_info_command import (
    PluginInfoCommandError,
    PluginInfoCommandInput,
    format_plugin_info_human,
    run_plugin_info_command,
)

_COMMAND_HELP = "Show detailed information about a single plugin."


def plugins_info(
    plugin_id: str = typer.Argument(..., help="Plugin id (or name) to inspect."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON to stdout.",
    ),
) -> None:
    """Show details for a single plugin."""
    try:
        result = run_plugin_info_command(
            PluginInfoCommandInput(plugin_id=plugin_id, include_install_record=not json_output)
        )
    except PluginInfoCommandError as exc:
        # Deterministic, concise error output.
        typer.echo(exc.message, err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps(result.plugin, indent=2, ensure_ascii=False))
        return

    typer.echo(format_plugin_info_human(result), nl=False)


def register(app: typer.Typer) -> None:
    """
    Register this command on an existing Typer application.

    The surrounding Thomas CLI loads command modules and calls `register`.
    """
    if getattr(app, "registered_callback", None) is None:

        @app.callback(invoke_without_command=True)
        def _root() -> None:
            return

    app.command("info", help=_COMMAND_HELP)(plugins_info)


# Provide a module-local Typer app for CLIs that discover a per-module app.
app = typer.Typer(help=_COMMAND_HELP, add_completion=False)
register(app)

# And a `COMMAND` symbol for loaders that expect a callable.
COMMAND = plugins_info
