"""CLI command: nodes reject-action.

This is a small wrapper around :func:`thomas.nodes.p048_nodes_reject_action.reject_node_action`.

Integration surfaces (for different Thomas CLI loaders):
- `COMMAND` / `CLICK_COMMAND`: Click command object
- `CLI_COMMANDS` / `COMMANDS`: list of commands
- `PARITY_COMMAND` / `PARITY_COMMANDS`: metadata used by parity/discovery layers
- `register(target)`: best-effort hook (Click group or argparse subparsers)
- `add_argparse_subcommand(subparsers)`: explicit argparse integration
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Optional

import click

try:
    import typer  # type: ignore
except Exception:  # pragma: no cover
    typer = None  # type: ignore

from thomas.nodes.p048_nodes_reject_action import NodesRejectActionError, NodesRejectActionInput, reject_node_action


def _execute(node_id: str, action_id: str, reason: Optional[str], state_dir: Optional[str]) -> Dict[str, Any]:
    payload = NodesRejectActionInput(node_id=node_id, action_id=action_id, reason=reason)
    return reject_node_action(payload, state_dir=state_dir).to_dict()


@click.command(name="reject-action")
@click.option("--node-id", required=True, type=str, help="Node identifier.")
@click.option("--action-id", required=True, type=str, help="Action identifier to reject.")
@click.option("--reason", required=False, type=str, help="Optional reason for rejection.")
@click.option(
    "--state-dir",
    required=False,
    type=click.Path(file_okay=False, dir_okay=True, path_type=str),
    help="Thomas state directory (overrides THOMAS_STATE_DIR).",
)
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def click_command(
    node_id: str,
    action_id: str,
    reason: Optional[str],
    state_dir: Optional[str],
    json_output: bool,
) -> None:
    """Reject a pending action for a node."""
    try:
        out = _execute(node_id=node_id, action_id=action_id, reason=reason, state_dir=state_dir)
        if json_output:
            click.echo(json.dumps(out, sort_keys=True))
            return

        res = out["result"]
        click.echo(f"Rejected action {res['action_id']} for node {res['node_id']}")
    except NodesRejectActionError as e:
        if json_output:
            click.echo(json.dumps(e.to_dict(), sort_keys=True))
            raise SystemExit(1)
        raise click.ClickException(f"{e.code}: {e.message}") from e


COMMAND = click_command
CLICK_COMMAND = click_command
CLI_COMMANDS = [click_command]
COMMANDS = CLI_COMMANDS


PARITY_COMMAND: Dict[str, Any] = {
    "group": "nodes",
    "name": "reject-action",
    "command": click_command,
    "supports_json": True,
    "module": __name__,
}
PARITY_COMMANDS = [PARITY_COMMAND]


def get_parity_commands():  # pragma: no cover
    return list(PARITY_COMMANDS)


# Optional Typer app for projects that compose subcommands as Typer apps.
if typer is not None:  # pragma: no cover
    app = typer.Typer(add_completion=False, help="Node action controls.")

    @app.command("reject-action")
    def typer_command(
        node_id: str = typer.Option(..., "--node-id", help="Node identifier."),
        action_id: str = typer.Option(..., "--action-id", help="Action identifier to reject."),
        reason: Optional[str] = typer.Option(None, "--reason", help="Optional reason for rejection."),
        state_dir: Optional[str] = typer.Option(None, "--state-dir", help="Thomas state directory."),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    ) -> None:
        try:
            out = _execute(node_id=node_id, action_id=action_id, reason=reason, state_dir=state_dir)
            if json_output:
                typer.echo(json.dumps(out, sort_keys=True))
                return

            res = out["result"]
            typer.echo(f"Rejected action {res['action_id']} for node {res['node_id']}")
        except NodesRejectActionError as e:
            if json_output:
                typer.echo(json.dumps(e.to_dict(), sort_keys=True))
                raise typer.Exit(code=1)
            raise typer.BadParameter(f"{e.code}: {e.message}") from e


def add_argparse_subcommand(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach this command to an argparse subparser collection."""
    p = subparsers.add_parser("reject-action", help="Reject a pending action for a node.")
    p.add_argument("--node-id", required=True, help="Node identifier.")
    p.add_argument("--action-id", required=True, help="Action identifier to reject.")
    p.add_argument("--reason", required=False, help="Optional reason for rejection.")
    p.add_argument("--state-dir", required=False, help="Thomas state directory.")
    p.add_argument("--json", dest="json_output", action="store_true", help="Emit machine-readable JSON.")
    p.set_defaults(_thomas_handler=_argparse_handler)
    return p


def _argparse_handler(args: argparse.Namespace) -> int:
    try:
        out = _execute(
            node_id=args.node_id,
            action_id=args.action_id,
            reason=getattr(args, "reason", None),
            state_dir=getattr(args, "state_dir", None),
        )
        if getattr(args, "json_output", False):
            print(json.dumps(out, sort_keys=True))
        else:
            res = out["result"]
            print(f"Rejected action {res['action_id']} for node {res['node_id']}")
        return 0
    except NodesRejectActionError as e:
        if getattr(args, "json_output", False):
            print(json.dumps(e.to_dict(), sort_keys=True))
        else:
            print(f"{e.code}: {e.message}")
        return 1


def register(target) -> None:  # pragma: no cover
    """Best-effort registration hook.

    Supports:
    - Click group / Typer app: ``add_command``
    - argparse subparsers: ``add_parser`` via :func:`add_argparse_subcommand`
    """
    if hasattr(target, "add_command"):
        target.add_command(click_command)
        return
    if hasattr(target, "add_parser"):
        add_argparse_subcommand(target)
