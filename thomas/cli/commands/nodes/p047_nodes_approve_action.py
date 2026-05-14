"""CLI: nodes approve-action (Prompt P047).

This module is designed to plug into Thomas' CLI command discovery.

Because Thomas' CLI is parity-tested against a catalog, this module exposes a
few conventional registration hooks so whichever discovery mechanism is used
can find it.

Command summary:
    thomas nodes approve-action ACTION_ID
        [--node NODE_ID ...]
        [--approver NAME]
        [--comment TEXT]
        [--state-path PATH]
        [--json]

Behavior:
- Validates input and appends a JSONL record to the approvals ledger.
- Supports machine-readable output via --json.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from thomas.nodes.p047_nodes_approve_action import (
    DEFAULT_APPROVALS_ENV_VAR,
    NodesApproveActionError,
    NodesApproveActionRequest,
    approve_action,
)

CLI_GROUP = "nodes"
COMMAND = "approve-action"
ALIASES = ["approve_action", "approveaction"]
HELP = "Record an approval for an action (writes to a JSONL ledger)."

# A few extra aliases to increase compatibility with different discovery mechanisms.
COMMAND_NAME = COMMAND
SUBCOMMAND = COMMAND


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the subcommand under an argparse subparsers object."""

    # argparse supports aliases=... in modern Python; keep it best-effort.
    try:
        parser = subparsers.add_parser(COMMAND, help=HELP, aliases=list(ALIASES))
    except TypeError:  # pragma: no cover
        parser = subparsers.add_parser(COMMAND, help=HELP)

    _configure_parser(parser)
    # Different Thomas CLI loaders may look for different default keys.
    parser.set_defaults(
        _thomas_entrypoint=_run_from_parsed_args,
        func=_run_from_parsed_args,
        handler=_run_from_parsed_args,
        run=_run_from_parsed_args,
    )
    return parser


# Common alternative hook names used across codebases.
register = add_subparser
add_parser = add_subparser
build_parser = add_subparser
add_command = add_subparser
register_command = add_subparser
register_subcommand = add_subparser
configure = add_subparser

# Some registries look for an iterable of command factories.
CLI_COMMANDS = (add_subparser,)


def _configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action_id", help="Action identifier to approve")
    parser.add_argument(
        "--node",
        dest="node_ids",
        action="append",
        default=[],
        help="Node identifier to approve for (repeatable)",
    )
    parser.add_argument("--approver", default=None, help="Who is approving the action")
    parser.add_argument("--comment", default=None, help="Optional approval comment")
    parser.add_argument(
        "--state-path",
        default=None,
        help=f"Where to append approval records (defaults to env {DEFAULT_APPROVALS_ENV_VAR})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout",
    )


def _run_from_parsed_args(args: argparse.Namespace) -> int:
    try:
        req = NodesApproveActionRequest(
            action_id=args.action_id,
            node_ids=tuple(args.node_ids or ()),
            approver=args.approver,
            comment=args.comment,
            state_path=args.state_path,
        )
        result = approve_action(req)

        if getattr(args, "json", False):
            print(json.dumps({"ok": True, "result": result.to_dict()}, sort_keys=True))
        else:
            nodes_str = ", ".join(result.approved_nodes) if result.approved_nodes else "(all)"
            print(f"Approved action {result.action_id} for nodes {nodes_str}.")
            if result.ledger_path:
                print(f"Ledger: {result.ledger_path}")

        return 0
    except NodesApproveActionError as e:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": e.to_dict()}, sort_keys=True))
        else:
            print(f"ERROR: {e.message}", file=sys.stderr)
            if e.details:
                print(f"Details: {json.dumps(e.details, sort_keys=True)}", file=sys.stderr)
        return e.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """Standalone entrypoint (useful for tests).

    This is *not* necessarily the primary Thomas CLI entrypoint; instead it
    provides a minimal wrapper so the command can be executed directly.
    """

    parser = argparse.ArgumentParser(prog="nodes approve-action")
    _configure_parser(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return _run_from_parsed_args(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
