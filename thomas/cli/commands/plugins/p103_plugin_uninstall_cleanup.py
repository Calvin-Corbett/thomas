"""CLI command: plugins uninstall-cleanup (P103).

This command is a thin wrapper around the Python API in
``thomas.plugins.p103_plugin_uninstall_cleanup``.

Machine-readable output is supported via ``--json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from thomas.plugins.p103_plugin_uninstall_cleanup import (
    PluginUninstallCleanupError,
    PluginUninstallCleanupRequest,
    run_plugin_uninstall_cleanup,
)

NAME = "uninstall-cleanup"
COMMAND_NAME = NAME


# Allow options after arguments (e.g. `... <plugin_id> --json`)
app = typer.Typer(
    add_completion=False,
    help="Remove leftover on-disk files for an uninstalled plugin.",
    context_settings={"allow_interspersed_args": True},
)


@app.callback(invoke_without_command=True)
def main(
    plugin_id: str = typer.Argument(..., help="Plugin id to clean up (directory under extensions/)."),  # noqa: B008
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be removed without deleting."),  # noqa: B008
    config_path: Path | None = typer.Option(
        None,
        "--config-path",
        exists=False,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to the Thomas config file (defaults via THOMAS_CONFIG_PATH or ~/.thomas/thomas.json).",  # noqa: E501
    ),
    state_dir: Path | None = typer.Option(
        None,
        "--state-dir",
        exists=False,
        file_okay=False,
        dir_okay=True,
        help="Override the Thomas state directory (defaults via THOMAS_STATE_DIR or config parent).",  # noqa: E501
    ),
    extensions_dir: Path | None = typer.Option(
        None,
        "--extensions-dir",
        exists=False,
        file_okay=False,
        dir_okay=True,
        help="Override the extensions root (defaults to <state_dir>/extensions).",  # noqa: E501
    ),
    prune_empty_parents: bool = typer.Option(
        True,
        "--prune-empty-parents/--no-prune-empty-parents",
        help="After removal, prune empty parent directories under extensions/.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),  # noqa: B008
) -> None:
    """Remove leftover plugin files.

    This is safe and idempotent: if the target directory does not exist, the
    command exits successfully with status=not_found.
    """

    req = PluginUninstallCleanupRequest(
        plugin_id=plugin_id,
        dry_run=dry_run,
        config_path=config_path,
        state_dir=state_dir,
        extensions_dir=extensions_dir,
        prune_empty_parents=prune_empty_parents,
    )

    try:
        result = run_plugin_uninstall_cleanup(req)
    except PluginUninstallCleanupError as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": exc.to_dict()}, sort_keys=True))
        else:
            typer.echo(f"ERROR [{exc.code}] {exc.message}", err=True)
        raise typer.Exit(code=2)

    if json_output:
        typer.echo(json.dumps({"ok": True, "result": result.to_dict()}, sort_keys=True))
        return

    typer.echo(f"plugin_id: {result.plugin_id}")
    typer.echo(f"status: {result.status}")

    if result.status in {"dry_run", "removed"}:
        prefix = "would remove" if result.status == "dry_run" else "removed"
        for p in result.removed:
            typer.echo(f"- {prefix}: {p}")

    for p in result.pruned_empty_dirs:
        typer.echo(f"- pruned empty dir: {p}")


def register(parent: typer.Typer) -> None:
    """Hook for CLIs that dynamically register subcommands."""

    parent.add_typer(app, name=NAME)


# Click command object for frameworks that expect it.
COMMAND = typer.main.get_command(app)
