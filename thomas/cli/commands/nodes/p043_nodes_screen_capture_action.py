"""CLI command for Prompt P043: Nodes screen capture action.

This module is designed to integrate with Thomas' CLI command discovery/parity
system. Different Thomas versions have used slightly different loader hooks, so
this module exports several common entrypoints:

- build_parser(subparsers)
- add_parser(subparsers)
- register(subparsers)

The command supports machine-readable output via --json.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from thomas.nodes.p043_nodes_screen_capture_action import (
    NodesScreenCaptureError,
    NodesScreenCaptureInputError,
    NodesScreenCaptureRequest,
    NodesScreenCaptureResult,
    parse_nodes_screen_capture_request,
    run_nodes_screen_capture_sync,
)

PROMPT_ID = "P043"

COMMAND_GROUP = "nodes"
COMMAND_NAME = "screen-capture"
COMMAND_ALIASES: tuple[str, ...] = ("screenshot", "capture-screen")

HELP = "Capture a screenshot from a node"


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("node_id", nargs="?", help="Target node identifier")
    parser.add_argument(
        "--node",
        dest="node_id_opt",
        help="Target node identifier (alternative to positional node_id)",
    )
    parser.add_argument(
        "--image-format",
        default="png",
        help="Image format (png, jpg, jpeg, webp)",
    )
    parser.add_argument(
        "--out",
        dest="save_path",
        default=None,
        help="Where to write the screenshot. If a directory (or ends with /), a filename is inferred.",
    )
    parser.add_argument(
        "--include-image",
        dest="include_image_b64",
        action="store_true",
        help="Include base64-encoded image bytes in output (useful with --json).",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout_s",
        type=float,
        default=30.0,
        help="Request timeout in seconds",
    )
    parser.add_argument(
        "--base-url",
        dest="nodes_base_url",
        default=None,
        help="Override nodes base URL (otherwise uses config/env)",
    )
    parser.add_argument(
        "--api-key",
        dest="nodes_api_key",
        default=None,
        help="API key for nodes service (otherwise uses config/env)",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Emit machine-readable JSON",
    )


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Primary registration hook used by many Thomas CLI loaders."""
    parser = subparsers.add_parser(COMMAND_NAME, help=HELP)
    _add_common_args(parser)
    parser.set_defaults(_thomas_handler=handle_args)
    return parser


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    return build_parser(subparsers)


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    return build_parser(subparsers)


def _resolve_node_id(args: argparse.Namespace) -> str:
    node_id = getattr(args, "node_id", None)
    node_id_opt = getattr(args, "node_id_opt", None)
    resolved = (node_id_opt or node_id or "").strip()
    if not resolved:
        raise NodesScreenCaptureInputError("node_id is required")
    return resolved


def _build_config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    if getattr(args, "nodes_base_url", None):
        cfg["nodes_base_url"] = str(args.nodes_base_url)
    if getattr(args, "nodes_api_key", None):
        cfg["nodes_api_key"] = str(args.nodes_api_key)
    return cfg


def handle_args(args: argparse.Namespace) -> int:
    """Command handler. Returns an exit code."""
    json_mode = bool(getattr(args, "json_mode", False))

    try:
        req_raw = {
            "node_id": _resolve_node_id(args),
            "image_format": getattr(args, "image_format", "png"),
            "save_path": getattr(args, "save_path", None),
            "include_image_b64": bool(getattr(args, "include_image_b64", False)),
            "timeout_s": getattr(args, "timeout_s", 30.0),
        }
        req: NodesScreenCaptureRequest = parse_nodes_screen_capture_request(req_raw)
        cfg = _build_config_from_args(args)
        res: NodesScreenCaptureResult = run_nodes_screen_capture_sync(req, config=cfg)

        payload = res.to_dict()
        if json_mode:
            print(json.dumps(payload, sort_keys=True))
        else:
            saved = payload["result"].get("saved_path")
            if saved:
                print(saved)
            else:
                print(f"Captured {payload['result']['bytes_captured']} bytes")
        return 0

    except NodesScreenCaptureError as e:
        if json_mode:
            print(json.dumps(e.to_dict(), sort_keys=True))
        else:
            print(str(e), file=sys.stderr)
        return 2


def cli_main(argv: Sequence[str] | None = None) -> int:
    """Standalone entrypoint (useful for unit tests)."""
    parser = argparse.ArgumentParser(prog=f"{COMMAND_GROUP} {COMMAND_NAME}")
    _add_common_args(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return handle_args(args)


# ---- CLI parity / discovery metadata -----------------------------------------
#
# Thomas versions vary slightly in how they discover commands. We provide:
# - PARITY_COMMAND (best-effort)
# - PARITY_COMMANDS (list wrapper)
# - get_parity_commands() (lazy accessor)
#
# Importing thomas.cli.parity_commands is safe in typical Thomas layouts because
# it primarily defines the ParityCommand type rather than importing all commands.
# If it isn't available, discovery can still happen through other mechanisms.


def _try_build_parity_command() -> Any:
    try:
        import inspect
        from dataclasses import fields, is_dataclass

        from thomas.cli.parity_commands import ParityCommand  # type: ignore
    except ImportError:
        return None

    values: dict[str, Any] = {
        "name": f"{COMMAND_GROUP} {COMMAND_NAME}",
        "command": f"{COMMAND_GROUP} {COMMAND_NAME}",
        "cmd": f"{COMMAND_GROUP} {COMMAND_NAME}",
        "help": HELP,
        "description": HELP,
        "group": COMMAND_GROUP,
        "category": COMMAND_GROUP,
        "aliases": list(COMMAND_ALIASES),
        "supports_json": True,
        "json": True,
        "machine_readable": True,
        "build_parser": build_parser,
        "add_parser": build_parser,
        "register": build_parser,
        "handler": handle_args,
        "run": handle_args,
        "execute": handle_args,
        "func": handle_args,
    }

    try:
        if is_dataclass(ParityCommand):
            param_names = {f.name for f in fields(ParityCommand)}
        else:
            sig = inspect.signature(ParityCommand)
            param_names = set(sig.parameters.keys())

        kwargs = {k: v for k, v in values.items() if k in param_names}

        try:
            return ParityCommand(**kwargs)
        except TypeError:
            inst = ParityCommand.__new__(ParityCommand)
            for k, v in kwargs.items():
                try:
                    object.__setattr__(inst, k, v)
                except (ValueError, TypeError):
                    setattr(inst, k, v)
            return inst
    except (ValueError, TypeError):
        return None


def get_parity_commands() -> list[Any]:
    cmd = _try_build_parity_command()
    return [cmd] if cmd is not None else []


PARITY_COMMAND = _try_build_parity_command()
COMMAND = PARITY_COMMAND
PARITY_COMMANDS = [c for c in [PARITY_COMMAND] if c is not None]
