"""CLI command: nodes pending-approvals.

This command prints either a human-readable table or machine-readable JSON.

Thomas-native behavior (no OpenClaw naming reuse).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from thomas.nodes.p046_nodes_pending_approvals import (
    ERROR_CONFIG_MISSING,
    ERROR_INVALID_INPUT,
    NodesPendingApprovalsError,
    NodesPendingApprovalsInput,
    nodes_pending_approvals,
)

COMMAND_GROUP = "nodes"
COMMAND_NAME = "pending-approvals"
COMMAND_PATH = (COMMAND_GROUP, COMMAND_NAME)


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `nodes pending-approvals` subcommand."""

    p = subparsers.add_parser(
        COMMAND_NAME,
        help="List node approval requests that are waiting for a decision",
        description="List node approval requests that are waiting for a decision.",
    )
    p.add_argument(
        "--state-dir",
        dest="state_dir",
        default=None,
        help="Override the Thomas state directory (advanced)",
    )
    p.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    # Different parts of Thomas use different default handler keys; set both.
    p.set_defaults(func=run, _thomas_cmd=run)
    return p


# Registry-friendly aliases (some Thomas registries use different names).
register = build_parser
add_parser = build_parser


def _format_human(payload: dict) -> str:
    approvals = payload.get("approvals") or []
    if not approvals:
        return "No nodes are pending approval."

    headers = ["node_id", "requested_at", "requested_by", "reason"]
    rows: list[list[str]] = []
    for item in approvals:
        rows.append([str(item.get(h, "") or "") for h in headers])

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    def fmt_row(values: Sequence[str]) -> str:
        return "  ".join(v.ljust(col_widths[i]) for i, v in enumerate(values))

    out_lines = [fmt_row(headers), fmt_row(["-" * w for w in col_widths])]
    out_lines.extend(fmt_row(r) for r in rows)
    return "\n".join(out_lines)


def _error_payload(exc: NodesPendingApprovalsError) -> dict:
    return {
        "ok": False,
        "error": {
            "code": getattr(exc, "code", "UNKNOWN"),
            "message": str(exc),
            "details": getattr(exc, "details", {}),
        },
    }


def run(args: argparse.Namespace) -> int:
    """Execute the command and return a process exit code."""

    try:
        out = nodes_pending_approvals(NodesPendingApprovalsInput(state_dir=args.state_dir))
        payload = {"ok": True, **out.to_dict()}
    except NodesPendingApprovalsError as exc:
        err = _error_payload(exc)
        if getattr(args, "as_json", False):
            print(json.dumps(err, indent=2, sort_keys=True))
        else:
            print(f"ERROR {err['error']['code']}: {err['error']['message']}", file=sys.stderr)
        # Map input/config issues to exit code 2, other failures to exit code 3.
        if getattr(exc, "code", "") in (ERROR_INVALID_INPUT, ERROR_CONFIG_MISSING):
            return 2
        return 3

    if getattr(args, "as_json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_human(payload))
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    """Standalone entrypoint for tests and direct execution."""

    parser = argparse.ArgumentParser(prog="thomas nodes pending-approvals")
    parser.add_argument("--state-dir", dest="state_dir", default=None)
    parser.add_argument("--json", dest="as_json", action="store_true")
    return run(parser.parse_args(argv))


# Convenience spec object for any registry that prefers data over callables.
COMMAND = {
    "group": COMMAND_GROUP,
    "name": COMMAND_NAME,
    "path": COMMAND_PATH,
    "register": build_parser,
    "run": run,
}


__all__ = [
    "COMMAND_GROUP",
    "COMMAND_NAME",
    "COMMAND_PATH",
    "COMMAND",
    "register",
    "add_parser",
    "build_parser",
    "run",
    "cli_main",
]
