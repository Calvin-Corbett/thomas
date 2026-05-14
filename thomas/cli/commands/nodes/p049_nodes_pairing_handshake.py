"""
CLI: thomas nodes pairing-handshake (P049)

Thin wrapper around thomas.nodes.p049_nodes_pairing_handshake.

This module exposes multiple "command surfaces" to maximize compatibility with
Thomas CLI registries:
- main(argv) -> exit code
- build_parser(parser=None) -> argparse parser
- add_parser(subparsers) -> argparse subparser (sets defaults.func)
- COMMAND / COMMAND_NAME / COMMAND_GROUP / PARITY_ID metadata
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from collections.abc import Sequence

from thomas.nodes.p049_nodes_pairing_handshake import (
    NodesPairingHandshakeError,
    NodesPairingHandshakeInput,
    NodesPairingHandshakeOutput,
    nodes_pairing_handshake,
)

COMMAND_NAME = "pairing-handshake"
COMMAND_GROUP = "nodes"
PARITY_ID = "p049"


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(
            prog=f"thomas {COMMAND_GROUP} {COMMAND_NAME}",
            description="Create or reuse a pending pairing request for a node.",
        )

    parser.add_argument("--node-id", required=True, help="Stable identifier for the node.")
    parser.add_argument("--display-name", default=None, help="Human-friendly node name.")
    parser.add_argument("--silent", action="store_true", help="Hint for higher layers (no security effect).")
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Override Thomas state directory (defaults to THOMAS_STATE_DIR or ~/.thomas).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    return obj


def _execute(args: argparse.Namespace) -> NodesPairingHandshakeOutput:
    state_dir = Path(args.state_dir) if getattr(args, "state_dir", None) else None
    inp = NodesPairingHandshakeInput(
        node_id=args.node_id,
        display_name=args.display_name,
        silent=bool(getattr(args, "silent", False)),
    )
    return nodes_pairing_handshake(inp, state_dir=state_dir)


def run(args: argparse.Namespace) -> int:
    """
    Entry point for registries that already parsed args and set defaults.func=run.
    """
    try:
        out = _execute(args)
    except NodesPairingHandshakeError as e:
        if getattr(args, "json", False):
            print(json.dumps(e.to_dict(), indent=2, sort_keys=True))
        else:
            print(f"ERROR [{e.code}] {e.message}", file=sys.stderr)
        return 2
    except Exception as e:  # pragma: no cover
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": {"code": "external_failure", "message": str(e)}}, indent=2))
        else:
            print(f"ERROR [external_failure] {e}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(out.to_dict(), indent=2, sort_keys=True, default=_to_jsonable))
    else:
        created = "created" if out.created else "reused"
        print(
            f"Pairing request {created}: request_id={out.request_id} node_id={out.node_id} "
            f"expires_at_ms={out.expires_at_ms}"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(args)


def add_parser(subparsers: Any) -> argparse.ArgumentParser:
    """
    Optional entry point used by argparse-based CLIs.

    Example registry behavior:
        p = add_parser(nodes_subparsers)
        # later:
        ns = root_parser.parse_args()
        exit(ns.func(ns))
    """
    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Create or reuse a pending pairing request for a node.",
    )
    build_parser(parser)
    parser.set_defaults(func=run)
    return parser


class CommandSpec(dict[str, Any]):
    """
    Loose command spec for registries that consume module-level metadata.
    """


COMMAND: CommandSpec = {
    "group": COMMAND_GROUP,
    "name": COMMAND_NAME,
    "parity_id": PARITY_ID,
    "main": main,
    "build_parser": build_parser,
    "add_parser": add_parser,
    "run": run,
}
