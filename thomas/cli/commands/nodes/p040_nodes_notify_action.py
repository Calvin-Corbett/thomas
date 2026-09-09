"""CLI command: nodes notify-action.

This module translates CLI flags into the core
:mod:`thomas.nodes.p040_nodes_notify_action` contract.

The Thomas CLI framework may load commands dynamically. To maximize compatibility
with different loader styles, this module exposes multiple common entry points:

- ``add_parser(subparsers)``: argparse-style registration
- ``register(subparsers)``: alias for add_parser
- ``run(args)``: execute a parsed argparse namespace
- ``COMMAND``: metadata dict that some loaders inspect

Machine-readable output is available via ``--json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

try:
    from thomas.marketplace.nodes.p040_nodes_notify_action import (
        NodesNotifyActionConfigError,
        NodesNotifyActionError,
        NodesNotifyActionExternalError,
        NodesNotifyActionInput,
        NodesNotifyActionInvalidInputError,
        notify_action,
        payload_from_json,
    )
except ImportError:  # pragma: no cover
    from thomas.nodes.p040_nodes_notify_action import (
        NodesNotifyActionConfigError,
        NodesNotifyActionError,
        NodesNotifyActionExternalError,
        NodesNotifyActionInput,
        NodesNotifyActionInvalidInputError,
        notify_action,
        payload_from_json,
    )


COMMAND_NAME = "notify-action"
COMMAND_ALIASES = ["notify_action"]
COMMAND_HELP = "Notify one or more nodes about an action."


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        COMMAND_NAME,
        aliases=COMMAND_ALIASES,
        help=COMMAND_HELP,
        description=COMMAND_HELP,
    )

    parser.add_argument(
        "--node",
        "--nodes",
        dest="node_ids",
        action="append",
        required=True,
        help="Target node id (repeatable).",
    )
    parser.add_argument("--action", required=True, help="Action name to notify.")
    parser.add_argument(
        "--payload",
        default=None,
        help="Optional JSON object payload.",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout_s",
        type=float,
        default=10.0,
        help="Timeout per node in seconds (default: 10).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    # Common dispatch attributes used across argparse-based CLIs.
    parser.set_defaults(_thomas_entrypoint=run, func=run, handler=run)
    return parser


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> argparse.ArgumentParser:
    """Alias for add_parser (some loaders use this name)."""
    return add_parser(subparsers)


def run(args: argparse.Namespace) -> int:
    """Execute the command from parsed argparse args."""
    json_mode = bool(getattr(args, "json", False))
    try:
        payload = payload_from_json(getattr(args, "payload", None))
        inp = NodesNotifyActionInput(
            node_ids=list(args.node_ids or []),
            action=str(args.action),
            payload=payload,
            timeout_s=float(args.timeout_s),
        )

        out = notify_action(inp)

        if json_mode:
            _print_json(out.to_json_dict())
        else:
            _print_human(out.to_json_dict())

        return 0 if out.ok else 1

    except (NodesNotifyActionInvalidInputError, NodesNotifyActionConfigError) as e:
        return _handle_error(e, json_mode=json_mode, exit_code=2)
    except NodesNotifyActionExternalError as e:
        return _handle_error(e, json_mode=json_mode, exit_code=3)
    except NodesNotifyActionError as e:
        return _handle_error(e, json_mode=json_mode, exit_code=1)


def main(argv: Sequence[str] | None = None) -> int:
    """Standalone entry point (primarily for unit tests)."""
    parser = argparse.ArgumentParser(prog="thomas nodes")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_parser(sub)
    ns = parser.parse_args(list(argv) if argv is not None else None)

    entry = getattr(ns, "_thomas_entrypoint", None)
    if callable(entry):
        return int(entry(ns))
    return 2


def _print_human(data: dict[str, Any]) -> None:
    action = data.get("action")
    results = data.get("results", [])
    ok = bool(data.get("ok"))

    prefix = "OK" if ok else "FAIL"
    print(f"{prefix}: notified action '{action}' to {len(results)} node(s)")
    for r in results:
        node_id = r.get("node_id")
        r_ok = r.get("ok")
        if r_ok:
            status = r.get("status")
            if status is None:
                print(f"  - {node_id}: ok")
            else:
                print(f"  - {node_id}: ok (HTTP {status})")
        else:
            code = r.get("error_code")
            msg = r.get("error_message")
            status = r.get("status")
            extra = []
            if status is not None:
                extra.append(f"HTTP {status}")
            if code:
                extra.append(str(code))
            extra_s = f" ({', '.join(extra)})" if extra else ""
            print(f"  - {node_id}: failed{extra_s}: {msg}")


def _handle_error(e: NodesNotifyActionError, *, json_mode: bool, exit_code: int) -> int:
    if json_mode:
        _print_json({"ok": False, "error": e.to_json_dict()})
    else:
        print(f"ERROR [{e.code}]: {e}", file=sys.stderr)
        if getattr(e, "details", None):
            print(json.dumps({"details": e.details}, sort_keys=True), file=sys.stderr)
    return exit_code


def _print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True))
    sys.stdout.write("\n")


COMMAND: dict[str, Any] = {
    "name": COMMAND_NAME,
    "aliases": COMMAND_ALIASES,
    "help": COMMAND_HELP,
    "add_parser": add_parser,
    "register": register,
    "run": run,
    "supports_json": True,
}
