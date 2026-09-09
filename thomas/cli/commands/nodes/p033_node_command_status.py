"""CLI: node command status.

This command is implemented in a Thomas-native way and supports machine-readable JSON
output via `--json`.
"""

from __future__ import annotations

import json
from typing import Any

import click

from thomas.nodes.p033_node_command_status import (
    NodeCommandStatusError,
    NodeCommandStatusRequest,
    get_node_command_status,
)

# These module-level constants are commonly used by command registries.
COMMAND_GROUP = "nodes"
COMMAND_NAME = "command-status"
COMMAND_HELP = "Show status for a previously-dispatched node command."

# Optional nesting support: some CLIs prefer `nodes command status <id>`.
NESTED_GROUP_NAME = "command"
NESTED_COMMAND_NAME = "status"


def _format_human(resp: dict[str, Any]) -> str:
    cmd = resp.get("command_id", "")
    node = resp.get("node_id") or "-"
    state = resp.get("state", "unknown")
    done = resp.get("done", False)
    success = resp.get("success")
    exit_code = resp.get("exit_code")

    parts = [f"Command: {cmd}", f"Node: {node}", f"State: {state}"]
    parts.append(f"Done: {done}")
    if success is not None:
        parts.append(f"Success: {success}")
    if exit_code is not None:
        parts.append(f"Exit code: {exit_code}")

    msg = resp.get("message")
    if msg:
        parts.append(f"Message: {msg}")

    if resp.get("stdout"):
        parts.append("Stdout:\n" + str(resp["stdout"]))
    if resp.get("stderr"):
        parts.append("Stderr:\n" + str(resp["stderr"]))

    return "\n".join(parts)


def _run(command_id: str, node_id: str | None, include_output: bool, as_json: bool) -> None:
    try:
        req = NodeCommandStatusRequest(
            command_id=command_id,
            node_id=node_id,
            include_output=include_output,
        )
        resp = get_node_command_status(req).to_dict()
    except NodeCommandStatusError as e:
        payload = e.to_dict()
        if as_json:
            click.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            click.echo(f"Error ({e.code}): {e.message}", err=True)
        raise SystemExit(e.exit_code)

    if as_json:
        click.echo(json.dumps(resp, indent=2, sort_keys=True))
    else:
        click.echo(_format_human(resp))


@click.command(name=COMMAND_NAME, help=COMMAND_HELP)
@click.argument("command_id", type=str)
@click.option("--node-id", type=str, default=None, help="Optional node identifier.")
@click.option(
    "--include-output/--no-include-output",
    default=False,
    help="Include stdout/stderr in the response when available.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON (response on stdout; errors on stdout with non-zero exit).",  # noqa: E501
)
def command_status_cli(command_id: str, node_id: str | None, include_output: bool, as_json: bool) -> None:
    _run(command_id, node_id, include_output, as_json)


@click.command(name=NESTED_COMMAND_NAME, help=COMMAND_HELP)
@click.argument("command_id", type=str)
@click.option("--node-id", type=str, default=None, help="Optional node identifier.")
@click.option(
    "--include-output/--no-include-output",
    default=False,
    help="Include stdout/stderr in the response when available.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON (response on stdout; errors on stdout with non-zero exit).",  # noqa: E501
)
def nested_status_cli(command_id: str, node_id: str | None, include_output: bool, as_json: bool) -> None:
    _run(command_id, node_id, include_output, as_json)


# Common aliases for registries that expect a module-level command object.
cli = command_status_cli
COMMAND = command_status_cli
CLICK_COMMAND = command_status_cli

# Optional exports for nested registration.
NESTED_COMMAND = nested_status_cli


def register_click(nodes_group: click.Group) -> None:
    """Register this command into an existing Click group.

    Adds:
      - `nodes command-status`
    And, if possible:
      - `nodes command status`
    """
    if COMMAND_NAME not in nodes_group.commands:
        nodes_group.add_command(command_status_cli)

    command_group = nodes_group.commands.get(NESTED_GROUP_NAME)
    if command_group is None:
        command_group = click.Group(name=NESTED_GROUP_NAME)
        nodes_group.add_command(command_group)

    if isinstance(command_group, click.Group) and NESTED_COMMAND_NAME not in command_group.commands:
        command_group.add_command(nested_status_cli, name=NESTED_COMMAND_NAME)


# Argparse support (some Thomas entrypoints use argparse-based dispatch).
def add_subparser(subparsers: Any) -> Any:
    """Add an argparse subparser for this command.

    Returns the created parser. The parser will store a callable at `func`.
    """
    parser = subparsers.add_parser(COMMAND_NAME, help=COMMAND_HELP)
    parser.add_argument("command_id", type=str, help="Command identifier")
    parser.add_argument("--node-id", dest="node_id", default=None, help="Optional node identifier")
    parser.add_argument(
        "--include-output",
        dest="include_output",
        action="store_true",
        help="Include stdout/stderr in the response when available",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON")
    parser.set_defaults(func=_run_from_argparse)
    return parser


def _run_from_argparse(args: Any) -> int:
    """Run command from an argparse Namespace; returns process exit code."""
    try:
        req = NodeCommandStatusRequest(
            command_id=args.command_id,
            node_id=getattr(args, "node_id", None),
            include_output=bool(getattr(args, "include_output", False)),
        )
        resp = get_node_command_status(req).to_dict()
    except NodeCommandStatusError as e:
        payload = e.to_dict()
        if bool(getattr(args, "as_json", False)):
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Error ({e.code}): {e.message}")
        return e.exit_code

    if bool(getattr(args, "as_json", False)):
        print(json.dumps(resp, indent=2, sort_keys=True))
    else:
        print(_format_human(resp))
    return 0
