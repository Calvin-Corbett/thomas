"""
Gateway uninstall command (CLI).

Thomas-native naming; Thomas-native naming.

This command reuses the core uninstall implementation from the server route module so:
- CLI and HTTP route share a single set of validations and error codes.
- Tests can target the core logic without needing an HTTP server.
"""

from __future__ import annotations

import json
from typing import Any

import click

try:
    import typer
except ImportError:  # pragma: no cover
    typer = None  # type: ignore[assignment]

from thomas.server.routes.gateway.p129_gateway_uninstall_command import (
    GatewayUninstallError,
    GatewayUninstallRequest,
    GatewayUninstallResult,
    uninstall_gateway,
)

COMMAND_GROUP = "gateway"
COMMAND_NAME = "uninstall"


def format_success(result: GatewayUninstallResult, *, json_output: bool) -> str:
    if json_output:
        return json.dumps({"ok": True, "result": result.to_payload()}, sort_keys=True)

    if result.already_absent:
        return "Gateway already absent. Nothing to do."

    removed = "\n".join(f"  - {p}" for p in result.removed_paths) if result.removed_paths else "  (none)"
    if result.dry_run:
        return f"Gateway uninstall preview.\nWould remove:\n{removed}"
    return f"Gateway uninstalled.\nRemoved:\n{removed}"


def format_error(err: GatewayUninstallError, *, json_output: bool) -> str:
    if json_output:
        return json.dumps({"ok": False, "error": err.to_payload()}, sort_keys=True)
    return f"Error [{err.code}]: {err}"


def run_gateway_uninstall(
    *,
    state_dir: str | None,
    dry_run: bool,
    purge_state: bool,
) -> GatewayUninstallResult:
    req = GatewayUninstallRequest(state_dir=state_dir, dry_run=dry_run, purge_state=purge_state)
    return uninstall_gateway(req)


@click.command(name=COMMAND_NAME)
@click.option(
    "--state-dir",
    default=None,
    help="Override the Thomas state directory (advanced / testing).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be removed without changing the filesystem.",
)
@click.option(
    "--purge-state",
    is_flag=True,
    help="Remove gateway state as well (reserved for future behavior).",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit machine-readable JSON to stdout.",
)
def click_command(
    state_dir: str | None,
    dry_run: bool,
    purge_state: bool,
    json_output: bool,
) -> None:
    try:
        result = run_gateway_uninstall(state_dir=state_dir, dry_run=dry_run, purge_state=purge_state)
        click.echo(format_success(result, json_output=json_output))
    except GatewayUninstallError as e:
        click.echo(format_error(e, json_output=json_output), err=not json_output)
        raise SystemExit(1)


COMMAND = click_command
CLICK_COMMAND = click_command
PARITY_COMMAND = click_command
ALIAS_COMMAND = click_command


def get_command() -> click.Command:
    return click_command


def register_typer(app: Any) -> None:
    """Register with a Typer app/group."""

    if typer is None:
        return

    @app.command(COMMAND_NAME)
    def _cmd(
        state_dir: str | None = typer.Option(
            None,
            "--state-dir",
            help="Override the Thomas state directory (advanced / testing).",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Show what would be removed without changing the filesystem.",
        ),
        purge_state: bool = typer.Option(
            False,
            "--purge-state",
            help="Remove gateway state as well (reserved for future behavior).",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON to stdout.",
        ),
    ) -> None:
        try:
            result = run_gateway_uninstall(state_dir=state_dir, dry_run=dry_run, purge_state=purge_state)
            print(format_success(result, json_output=json_output))
        except GatewayUninstallError as e:
            print(format_error(e, json_output=json_output))
            raise typer.Exit(code=1)


# Common discovery hooks / aliases used by different CLI loaders.
register = register_typer
register_command = register_typer
init = register_typer
setup = register_typer
