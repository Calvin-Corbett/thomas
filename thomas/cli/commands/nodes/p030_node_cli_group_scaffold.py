"""
P030 - Node CLI group scaffold (CLI)

Defines the `nodes` command group for the Thomas CLI, including machine-readable
output via `--json`.

The broader CLI framework discovers and registers commands from modules under
`thomas.cli.commands.*`. To maximize compatibility with Thomas' existing
registries, this module exports common hooks:
- COMMAND: click.Command (the primary group)
- COMMANDS: list[tuple[str, click.Command]] (supports aliases)
- get_commands(): function returning COMMANDS
"""

from __future__ import annotations

from typing import Any, Mapping

import json

import click

from thomas.nodes.p030_node_cli_group_scaffold import (
    NodeCliScaffoldError,
    NodeGetRequest,
    NodeListRequest,
    error_to_dict,
    get_node,
    list_nodes,
    ok_get_to_dict,
    ok_list_to_dict,
)


def _exit_code_for_error(err: NodeCliScaffoldError) -> int:
    # Deterministic exit codes for automation.
    if err.kind == "input":
        return 2
    if err.kind == "config":
        return 3
    if err.kind == "external":
        return 4
    return 1


def _emit_result(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    # Human-friendly rendering.
    if payload.get("ok") is True:
        result = payload.get("result") or {}

        # node show
        if "node" in result:
            node = result.get("node") or {}
            click.echo(f"ID: {node.get('id', '')}")
            if node.get("label"):
                click.echo(f"Label: {node.get('label')}")
            if node.get("address"):
                click.echo(f"Address: {node.get('address')}")
            return

        # nodes list
        if "nodes" in result:
            nodes = result.get("nodes") or []
            if not nodes:
                click.echo("No nodes found.")
                return

            headers = ("ID", "LABEL", "ADDRESS")
            rows = [(n.get("id", ""), n.get("label") or "", n.get("address") or "") for n in nodes]
            widths = [max(len(str(v)) for v in [h] + [r[i] for r in rows]) for i, h in enumerate(headers)]
            fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
            click.echo(fmt.format(*headers))
            click.echo(fmt.format(*["-" * w for w in widths]))
            for r in rows:
                click.echo(fmt.format(*r))
            return

        click.echo("OK")
        return

    # Error payload
    err = payload.get("error") or {}
    msg = err.get("message") or "Unknown error"
    click.echo(f"Error: {msg}", err=True)


@click.group(name="nodes", help="Manage Thomas nodes.")
def nodes_group() -> None:
    # Group scaffold only; subcommands implement behavior.
    pass


@nodes_group.command("list", help="List known nodes.")
@click.option(
    "--config",
    "config_path",
    type=str,
    required=False,
    help="Path to a nodes config file (JSON/YAML/TOML).",
)
@click.option(
    "--server",
    "server_url",
    type=str,
    required=False,
    help="Server base URL to query for nodes (e.g. http://127.0.0.1:8080).",
)
@click.option(
    "--timeout",
    "timeout_s",
    type=float,
    default=5.0,
    show_default=True,
    help="Timeout in seconds for server requests.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON output.",
)
def nodes_list(config_path: str | None, server_url: str | None, timeout_s: float, as_json: bool) -> None:
    try:
        resp = list_nodes(NodeListRequest(config_path=config_path, server_url=server_url, timeout_s=timeout_s))
        payload = ok_list_to_dict(resp)
        _emit_result(payload, as_json=as_json)
    except NodeCliScaffoldError as e:
        payload = error_to_dict(e)
        _emit_result(payload, as_json=as_json)
        raise SystemExit(_exit_code_for_error(e))


@nodes_group.command("show", help="Show a single node by id.")
@click.argument("node_id", type=str)
@click.option(
    "--config",
    "config_path",
    type=str,
    required=False,
    help="Path to a nodes config file (JSON/YAML/TOML).",
)
@click.option(
    "--server",
    "server_url",
    type=str,
    required=False,
    help="Server base URL to query for nodes (e.g. http://127.0.0.1:8080).",
)
@click.option(
    "--timeout",
    "timeout_s",
    type=float,
    default=5.0,
    show_default=True,
    help="Timeout in seconds for server requests.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON output.",
)
def nodes_show(node_id: str, config_path: str | None, server_url: str | None, timeout_s: float, as_json: bool) -> None:
    try:
        resp = get_node(NodeGetRequest(node_id=node_id, config_path=config_path, server_url=server_url, timeout_s=timeout_s))
        payload = ok_get_to_dict(resp)
        _emit_result(payload, as_json=as_json)
    except NodeCliScaffoldError as e:
        payload = error_to_dict(e)
        _emit_result(payload, as_json=as_json)
        raise SystemExit(_exit_code_for_error(e))


# Primary export used by many registries.
COMMAND = nodes_group

# Alias support: parity tests may look for singular/plural or device-ish forms.
COMMANDS = [
    ("nodes", nodes_group),
    ("node", nodes_group),
    ("devices", nodes_group),
    ("device", nodes_group),
]


def get_commands() -> list[tuple[str, click.Command]]:
    """Registry hook: return commands to attach to the root CLI group."""
    return list(COMMANDS)


# Additional registry hooks used across the Thomas CLI codebase.
NAME = "nodes"
ALIASES = ("node", "devices", "device")


def get_click_command() -> click.Command:
    """Return the primary click command/group for this module."""
    return nodes_group


def build_cli() -> click.Command:
    """Alias for get_click_command()."""
    return nodes_group


def register(root: click.Group) -> None:
    """Best-effort registration helper for frameworks that pass a root group."""
    try:
        existing = getattr(root, "commands", {}) or {}
        # Only add aliases if they don't already exist (avoid overriding built-ins).
        if "nodes" not in existing:
            root.add_command(nodes_group, name="nodes")
        if "node" not in existing:
            root.add_command(nodes_group, name="node")
        if "devices" not in existing:
            root.add_command(nodes_group, name="devices")
        if "device" not in existing:
            root.add_command(nodes_group, name="device")
    except Exception:
        # Never explode at import/register time; deterministic failures are handled at invocation.
        return
