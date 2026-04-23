"""thomas.cli.commands.nodes.p038_nodes_list_and_status

CLI wiring for the Thomas-native "nodes list/status" behavior.

This module aims to be compatible with common argparse-based command discovery:
it exposes both `register()` and `add_parser()` entrypoints, plus light metadata.

Machine-readable output is supported via `--json`.

"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping

from thomas.nodes.p038_nodes_list_and_status import (
    NodesConfigError,
    NodesExternalFailureError,
    NodesInvalidInputError,
    NodesListAndStatusError,
    NodesListAndStatusRequest,
    NodesListAndStatusResponse,
    list_nodes_and_status,
    load_config_from_path,
)

COMMAND_GROUP = "nodes"
COMMAND_NAME = "list"
COMMAND_ALIASES = ["ls", "status", "list-status"]
COMMAND_FULL_NAME = f"{COMMAND_GROUP} {COMMAND_NAME}"

# Optional metadata hook for frameworks that index command modules.
COMMAND_SPEC: dict[str, Any] = {
    "group": COMMAND_GROUP,
    "name": COMMAND_NAME,
    "aliases": list(COMMAND_ALIASES),
    "full_name": COMMAND_FULL_NAME,
    "supports_json": True,
}


def register(target: Any) -> None:
    """Register this command with an argparse CLI.

    `target` may be:
    - argparse.ArgumentParser
    - argparse._SubParsersAction (root or nodes-group)

    The function does nothing for unknown target types.
    """
    if isinstance(target, argparse.ArgumentParser):
        subparsers = _ensure_subparsers(target, dest="command")
        _register_with_subparsers(subparsers)
        return

    # argparse._SubParsersAction has add_parser(). We avoid importing its type.
    if hasattr(target, "add_parser") and hasattr(target, "choices"):
        _register_with_subparsers(target)
        return


# Common alias used in other command modules.
add_parser = register


def _register_with_subparsers(subparsers: Any) -> None:
    # If we're already inside the nodes group, add the subcommand directly.
    if _looks_like_nodes_group(subparsers):
        nodes_subparsers = subparsers
    else:
        nodes_parser = getattr(subparsers, "choices", {}).get(COMMAND_GROUP)
        if nodes_parser is None:
            nodes_parser = subparsers.add_parser(COMMAND_GROUP, help="Manage configured Thomas nodes")
        nodes_subparsers = _ensure_subparsers(nodes_parser, dest="nodes_command")

    # Avoid clobbering if already registered.
    if getattr(nodes_subparsers, "choices", {}).get(COMMAND_NAME) is not None:
        return

    existing = set(getattr(nodes_subparsers, "choices", {}).keys())
    aliases = [a for a in COMMAND_ALIASES if a not in existing and a != COMMAND_NAME]

    cmd_parser = nodes_subparsers.add_parser(
        COMMAND_NAME,
        aliases=aliases,
        help="List configured nodes and probe reachability",
        description="List configured nodes and probe reachability (TCP connect)",
    )

    cmd_parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="Connection timeout per node in seconds (default: 2.0)",
    )
    cmd_parser.add_argument(
        "--max-concurrency",
        type=int,
        default=20,
        help="Max concurrent probes (default: 20)",
    )
    cmd_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail (non-zero exit) if any node is unreachable",
    )

    _maybe_add_flag(
        cmd_parser,
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    cmd_parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """Argparse handler. Returns an exit code (0 on success)."""
    json_mode = bool(getattr(args, "json", False))

    request = NodesListAndStatusRequest(
        timeout_s=float(args.timeout),
        max_concurrency=int(args.max_concurrency),
        strict=bool(args.strict),
    )

    config = _extract_config_from_args(args)

    try:
        response = list_nodes_and_status(request, config=config)
    except NodesListAndStatusError as e:
        _emit_error(e, json_mode=json_mode)
        return _exit_code_for_error(e)

    _emit_success(response, json_mode=json_mode)
    return 0


def _extract_config_from_args(args: argparse.Namespace) -> Mapping[str, Any] | None:
    # Many Thomas entrypoints attach a resolved config mapping onto args.
    for attr in ("thomas_config", "config", "cfg", "settings"):
        val = getattr(args, attr, None)
        if isinstance(val, Mapping):
            return val
        if isinstance(val, str) and val.strip():
            return load_config_from_path(val.strip())

    # Some entrypoints pass the config path separately.
    for attr in ("config_path", "config_file", "settings_path"):
        val = getattr(args, attr, None)
        if isinstance(val, str) and val.strip():
            return load_config_from_path(val.strip())

    return None


def _emit_success(response: NodesListAndStatusResponse, *, json_mode: bool) -> None:
    if json_mode:
        payload = {"ok": True, "result": response.to_dict()}
        print(json.dumps(payload, sort_keys=True))
        return

    print(f"{response.online_count} online / {response.offline_count} offline")
    for n in response.nodes:
        status = "online" if n.online else "offline"
        latency = f" ({n.latency_ms}ms)" if n.online and n.latency_ms is not None else ""
        err = f" - {n.error}" if (not n.online and n.error) else ""
        label = f" [{n.label}]" if n.label else ""
        print(f"- {n.node_id}{label}: {status}{latency} @ {n.address}{err}")


def _emit_error(err: NodesListAndStatusError, *, json_mode: bool) -> None:
    if json_mode:
        payload = {"ok": False, "error": err.to_dict()}
        print(json.dumps(payload, sort_keys=True))
        return

    print(f"ERROR ({err.code}): {err}", file=sys.stderr)
    if err.details:
        print(json.dumps(err.details, sort_keys=True), file=sys.stderr)


def _exit_code_for_error(err: NodesListAndStatusError) -> int:
    if isinstance(err, NodesInvalidInputError):
        return 2
    if isinstance(err, NodesConfigError):
        return 3
    if isinstance(err, NodesExternalFailureError):
        return 4
    return 1


def _ensure_subparsers(parser: argparse.ArgumentParser, *, dest: str) -> Any:
    for action in getattr(parser, "_actions", []):
        if isinstance(action, argparse._SubParsersAction):
            return action
    return parser.add_subparsers(dest=dest)


def _looks_like_nodes_group(subparsers: Any) -> bool:
    prog_prefix = getattr(subparsers, "_prog_prefix", "")
    return isinstance(prog_prefix, str) and prog_prefix.strip().endswith(f" {COMMAND_GROUP}")


def _maybe_add_flag(parser: argparse.ArgumentParser, *args: Any, **kwargs: Any) -> None:
    option_strings = set(getattr(parser, "_option_string_actions", {}).keys())
    for a in args:
        if isinstance(a, str) and a in option_strings:
            return
    parser.add_argument(*args, **kwargs)


__all__ = [
    "COMMAND_ALIASES",
    "COMMAND_FULL_NAME",
    "COMMAND_GROUP",
    "COMMAND_NAME",
    "COMMAND_SPEC",
    "add_parser",
    "register",
    "run",
]
