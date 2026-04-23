"""CLI: plugin command registry bridge.

This command provides a diagnostic + automation surface for the plugin command
registry bridge.

Capabilities:
- Emit request/response schemas (machine-readable)
- List discovered plugin command names
- Invoke a plugin command via the bridge

Owned by prompt P106.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import click

from thomas.plugins.p106_plugin_command_registry_bridge import (
    CommandRegistryAdapter,
    PluginCommandBridgeError,
    discover_command_registry,
    dispatch_plugin_command,
    request_schema,
    response_schema,
)


def _load_args(args_json: Optional[str], args_file: Optional[Path]) -> Dict[str, Any]:
    if args_json and args_file:
        raise PluginCommandBridgeError(
            code="INVALID_INPUT",
            message="Provide only one of --args-json or --args-file.",
            details=None,
        )

    if args_file is not None:
        try:
            args_json = args_file.read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise PluginCommandBridgeError(
                code="MISSING_CONFIG",
                message="Args file not found.",
                details={"path": str(args_file)},
            ) from e

    if not args_json:
        return {}

    try:
        value = json.loads(args_json)
    except json.JSONDecodeError as e:
        raise PluginCommandBridgeError(
            code="INVALID_INPUT",
            message="Args must be valid JSON.",
            details={"error": str(e)},
        ) from e

    if not isinstance(value, dict):
        raise PluginCommandBridgeError(
            code="INVALID_INPUT",
            message="Args JSON must decode to an object.",
            details={"type": type(value).__name__},
        )

    return value


@click.command(name="plugin-command-registry-bridge")
@click.option("--schema", "schema_mode", is_flag=True, help="Print the bridge request/response JSON schemas.")
@click.option("--list", "list_mode", is_flag=True, help="List discovered plugin command names.")
@click.option("--command", "command_name", type=str, default=None, help="Invoke a specific plugin command by name.")
@click.option("--args-json", "args_json", type=str, default=None, help="JSON object of arguments to pass to the command.")
@click.option(
    "--args-file",
    "args_file",
    type=click.Path(path_type=Path, dir_okay=False, exists=False),
    default=None,
    help="Path to a JSON file of arguments to pass to the command.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON output.")
def cli(
    schema_mode: bool,
    list_mode: bool,
    command_name: Optional[str],
    args_json: Optional[str],
    args_file: Optional[Path],
    json_mode: bool,
) -> None:
    """Bridge plugin commands into a tool-friendly invocation surface."""
    try:
        # Default behavior:
        # - In JSON mode: emit schemas (safe for automation)
        # - In human mode: list commands (if registry available)
        default_mode = (not schema_mode) and (not list_mode) and (command_name is None)

        if schema_mode or (json_mode and default_mode):
            payload = {"request_schema": request_schema(), "response_schema": response_schema()}
            _emit(payload, json_mode=json_mode)
            return

        registry = discover_command_registry()

        if list_mode or (default_mode and not json_mode):
            if registry is None:
                raise PluginCommandBridgeError(
                    code="MISSING_CONFIG",
                    message="No plugin command registry could be discovered.",
                    details=None,
                )
            commands = CommandRegistryAdapter(registry).list_commands()
            _emit({"ok": True, "commands": commands}, json_mode=json_mode)
            return

        # Invoke
        args = _load_args(args_json, args_file)

        result = dispatch_plugin_command(
            {"command": command_name, "args": args},
            command_registry=registry,
        )
        _emit(result, json_mode=json_mode)
        if not bool(result.get("ok")):
            raise SystemExit(1)

    except PluginCommandBridgeError as e:
        payload = {"ok": False, "error": {"code": e.code, "message": e.message, "details": e.details}}
        _emit(payload, json_mode=json_mode)
        raise SystemExit(1)


def _emit(payload: Any, *, json_mode: bool) -> None:
    # For now, human mode still prints JSON (it's unambiguous and copy/paste friendly).
    click.echo(json.dumps(payload, indent=2, sort_keys=True))


# Conventional module-level handles for command loaders.
COMMAND = cli


def get_command() -> click.Command:
    return cli
