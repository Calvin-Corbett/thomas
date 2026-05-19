"""CLI wrapper for Thomas node install (P031).

This module intentionally stays small and boring:
it parses CLI flags, calls the core installer, and prints either human output
or machine-readable JSON (``--json``).

To maximize compatibility with different Thomas CLI dispatchers, this file
exposes a few common entrypoints/aliases: ``register`` / ``add_parser``,
``run_from_parsed`` / ``run``, and ``main`` / ``cli``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from thomas.nodes.p031_node_command_install import (
    NodeInstallError,
    NodeInstallRequest,
    install_node_command,
    render_install_error_json,
    render_install_result_human,
)

PROMPT_ID = "p031"

COMMAND_GROUP = "node"
COMMAND_NAME = "install"
COMMAND = "node install"
PARITY_COMMAND = COMMAND
HELP = "Install a local node host service"


def build_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Attach arguments to an argparse parser."""

    parser.add_argument("--host", help="Gateway host", default=None)
    parser.add_argument("--port", type=int, help="Gateway port", default=None)
    parser.add_argument("--tls", action="store_true", help="Use TLS for the gateway connection")
    parser.add_argument(
        "--tls-fingerprint",
        dest="tls_fingerprint",
        default=None,
        help="Expected TLS certificate fingerprint (sha256)",
    )
    parser.add_argument("--node-id", dest="node_id", default=None, help="Override node id")
    parser.add_argument("--display-name", dest="display_name", default=None, help="Override display name")
    parser.add_argument("--runtime", default="python", help="Runtime (default: python)")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing install")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def register(subparsers: Any) -> argparse.ArgumentParser:
    """Register this command on an argparse subparsers object."""

    parser = subparsers.add_parser(COMMAND_NAME, help=HELP)
    build_parser(parser)
    # Different dispatch layers use different default keys; set both.
    parser.set_defaults(func=run_from_parsed, _thomas_handler=run_from_parsed)
    return parser


# Common alias name.
add_parser = register


def run_from_parsed(args: argparse.Namespace) -> int:
    """Execute the command from parsed argparse args."""

    req = NodeInstallRequest(
        host=args.host,
        port=args.port,
        tls=bool(args.tls),
        tls_fingerprint=args.tls_fingerprint,
        node_id=args.node_id,
        display_name=args.display_name,
        runtime=args.runtime,
        force=bool(args.force),
    )

    try:
        result = install_node_command(req)
    except NodeInstallError as e:
        if getattr(args, "json", False):
            print(json.dumps(render_install_error_json(e), sort_keys=True), file=sys.stdout)
        else:
            print(f"ERROR[{e.code}]: {e}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), sort_keys=True), file=sys.stdout)
    else:
        print(render_install_result_human(result), file=sys.stdout)
    return 0


# Common alias name.
run = run_from_parsed


def main(argv: Sequence[str] | None = None) -> int:
    """Standalone entrypoint."""

    parser = build_parser(argparse.ArgumentParser(prog="thomas node install", add_help=True))
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_from_parsed(args)


# Common alias name.
cli = main
entrypoint = main


__all__ = [
    "PROMPT_ID",
    "COMMAND_GROUP",
    "COMMAND_NAME",
    "COMMAND",
    "PARITY_COMMAND",
    "HELP",
    "build_parser",
    "register",
    "add_parser",
    "run_from_parsed",
    "run",
    "main",
    "cli",
    "entrypoint",
]
