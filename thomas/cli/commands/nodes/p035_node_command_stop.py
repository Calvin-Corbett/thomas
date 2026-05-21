"""CLI command: nodes stop.

This command is implemented as a Thomas-native node lifecycle operation.

The surrounding Thomas CLI framework is responsible for wiring this module into
the overall command tree. To maximize compatibility with different loaders and
parity layers, this module exposes:

- ``command``: a Click-compatible command object
- ``get_command()``: returns the Click-compatible command
- ``app`` / ``typer_app``: a Typer app (only if Typer is available)

The command supports ``--json`` output for automation.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

try:  # Typer is optional; Click is the hard dependency here.
    import typer  # type: ignore
except ImportError:  # pragma: no cover
    typer = None  # type: ignore

try:
    from thomas.marketplace.nodes.p035_node_command_stop import (
        NodeCommandStopError,
        NodeCommandStopInput,
        node_command_stop,
    )
except ImportError:  # pragma: no cover
    from thomas.nodes.p035_node_command_stop import (
        NodeCommandStopError,
        NodeCommandStopInput,
        node_command_stop,
    )

COMMAND_GROUP = "nodes"
COMMAND_NAME = "stop"


def _emit_json(obj: object) -> None:
    click.echo(json.dumps(obj, sort_keys=True))


def _run_stop(
    *,
    node_id: str,
    force: bool,
    timeout_s: float | None,
    config_path: str | None,
    json_output: bool,
) -> None:
    inp = NodeCommandStopInput(
        node_id=node_id,
        force=force,
        timeout_s=timeout_s,
        config_path=config_path,
    )

    try:
        out = node_command_stop(inp)
        if json_output:
            _emit_json(out.to_json())
        else:
            click.echo(out.message)
    except NodeCommandStopError as e:
        if json_output:
            _emit_json({"ok": False, "error": e.to_json()})
        else:
            click.echo(f"Error [{e.code}]: {e}", err=True)
        raise click.exceptions.Exit(code=2) from e


@click.command(name=COMMAND_NAME)
@click.argument("node_id")
@click.option("--force", is_flag=True, help="Force stop")
@click.option("--timeout", "timeout_s", type=float, default=None, help="Timeout (seconds)")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, dir_okay=False, file_okay=True, readable=True, path_type=str),
    default=None,
    help="Optional config file (JSON/YAML)",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output")
def click_command(
    node_id: str,
    force: bool,
    timeout_s: float | None,
    config_path: str | None,
    json_output: bool,
) -> None:
    """Stop a node."""
    _run_stop(
        node_id=node_id,
        force=force,
        timeout_s=timeout_s,
        config_path=config_path,
        json_output=json_output,
    )


def get_command():
    """Return a Click-compatible command for registration."""
    return click_command


# Common aliases used by various command loaders.
command = click_command

if typer is not None:
    typer_app = typer.Typer(add_completion=False, help="Node lifecycle commands")  # type: ignore[attr-defined]
    app = typer_app  # alias

    @typer_app.command(COMMAND_NAME)  # type: ignore[attr-defined]
    def stop(
        node_id: str = typer.Argument(..., help="Node identifier to stop"),  # type: ignore[attr-defined]
        force: bool = typer.Option(False, "--force", help="Force stop"),  # type: ignore[attr-defined]
        timeout_s: float | None = typer.Option(  # type: ignore[attr-defined]
            None,
            "--timeout",
            help="Timeout (seconds) to wait for the stop operation",
            min=0,
        ),
        config_path: Path | None = typer.Option(  # type: ignore[attr-defined]
            None,
            "--config",
            exists=False,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Optional config file (JSON/YAML)",
        ),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON output"),  # type: ignore[attr-defined]
    ) -> None:
        """Stop a node."""
        _run_stop(
            node_id=node_id,
            force=force,
            timeout_s=timeout_s,
            config_path=str(config_path) if config_path is not None else None,
            json_output=json_output,
        )
else:
    typer_app = None  # type: ignore
    app = None  # type: ignore
