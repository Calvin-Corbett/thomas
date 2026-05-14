"""CLI: resolve the destination assistant for an inbound message.

This is a thin wrapper around:
  thomas.messages.p072_message_channel_specific_route_resolver

The command is intended for two use cases:
1) Humans debugging routing rules
2) Automation tooling (use --json or --schema)

The module is written to be import-safe: importing it should not perform any
network I/O or have side effects.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from thomas.messages.p072_message_channel_specific_route_resolver import (
    InvalidRouteConfigError,
    InvalidRouteInputError,
    MessagePeer,
    MessageRouteContext,
    MessageRouteResolutionError,
    RouteExternalFailureError,
    context_from_mapping,
    load_routing_config,
    resolve_message_route,
    route_resolution_json_schema,
)

COMMAND_NAME = "messages.resolve-route"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMMAND_NAME,
        description="Resolve which assistant should handle an inbound message (deterministic).",
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to routing config JSON.",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the JSON schema for --json output and exit.",
    )

    ctx_group = parser.add_mutually_exclusive_group(required=False)
    ctx_group.add_argument(
        "--context-json",
        help="Context as a JSON object string.",
    )
    ctx_group.add_argument(
        "--context-file",
        help="Path to a JSON file containing the context object.",
    )

    # Flag-based context (used when --context-json/--context-file are not provided)
    parser.add_argument("--channel", help="Inbound message channel (e.g. slack, discord, telegram).")
    parser.add_argument("--account-id", help="Channel account id (if applicable).")

    parser.add_argument("--peer-kind", help="Peer kind (direct/group/channel).")
    parser.add_argument("--peer-id", help="Peer id.")

    parser.add_argument("--parent-peer-kind", help="Parent peer kind for threads (direct/group/channel).")
    parser.add_argument("--parent-peer-id", help="Parent peer id for threads.")

    parser.add_argument("--guild-id", help="Discord guild id.")
    parser.add_argument(
        "--role",
        action="append",
        default=None,
        dest="roles",
        help="Discord role id. May be repeated.",
    )
    parser.add_argument("--team-id", help="Slack team id.")

    return parser


def _load_context(args: argparse.Namespace) -> MessageRouteContext:
    if args.context_json:
        try:
            raw = json.loads(args.context_json)
        except json.JSONDecodeError as e:
            raise InvalidRouteInputError(
                "invalid_input",
                "--context-json is not valid JSON.",
                details={"line": e.lineno, "col": e.colno},
            ) from e
        return context_from_mapping(raw)

    if args.context_file:
        try:
            text = Path(args.context_file).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise RouteExternalFailureError(
                "context_read_failed",
                "Failed to read context file.",
                details={"path": args.context_file, "os_error": e.__class__.__name__},
            ) from e
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            raise InvalidRouteInputError(
                "invalid_input",
                "Context file is not valid JSON.",
                details={"path": args.context_file, "line": e.lineno, "col": e.colno},
            ) from e
        return context_from_mapping(raw)

    # Flag-based context
    if not args.channel:
        raise InvalidRouteInputError(
            "invalid_input",
            "--channel is required when not using --context-json/--context-file.",
            details={},
        )

    peer = None
    if args.peer_kind or args.peer_id:
        if not (args.peer_kind and args.peer_id):
            raise InvalidRouteInputError(
                "invalid_input",
                "--peer-kind and --peer-id must be provided together.",
                details={},
            )
        peer = MessagePeer(kind=args.peer_kind, id=args.peer_id)

    parent_peer = None
    if args.parent_peer_kind or args.parent_peer_id:
        if not (args.parent_peer_kind and args.parent_peer_id):
            raise InvalidRouteInputError(
                "invalid_input",
                "--parent-peer-kind and --parent-peer-id must be provided together.",
                details={},
            )
        parent_peer = MessagePeer(kind=args.parent_peer_kind, id=args.parent_peer_id)

    roles = tuple(args.roles) if args.roles else None

    return MessageRouteContext(
        channel=args.channel,
        account_id=args.account_id,
        peer=peer,
        parent_peer=parent_peer,
        guild_id=args.guild_id,
        roles=roles,
        team_id=args.team_id,
    )


def run(argv: Sequence[str] | None = None) -> int:
    """Run the command.

    Returns a process-style exit code.
    """

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.schema:
        sys.stdout.write(json.dumps(route_resolution_json_schema(), indent=2, sort_keys=True) + "\n")
        return 0

    try:
        config = load_routing_config(args.config)
        ctx = _load_context(args)
        resolution = resolve_message_route(ctx, config)

        if args.json:
            sys.stdout.write(json.dumps(resolution.to_dict(), indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(
                f"assistant_id={resolution.assistant_id} tier={resolution.tier} rule_index={resolution.rule_index}\n"
            )
        return 0

    except MessageRouteResolutionError as e:
        if args.json:
            sys.stdout.write(json.dumps(e.to_dict(), indent=2, sort_keys=True) + "\n")
        else:
            sys.stderr.write(f"{e.payload.code}: {e.payload.message}\n")
        # Deterministic exit codes: 2 for user/config errors, 1 for external.
        if isinstance(e, (InvalidRouteInputError, InvalidRouteConfigError)):
            return 2
        if isinstance(e, RouteExternalFailureError):
            return 1
        return 1


def main() -> None:  # pragma: no cover
    raise SystemExit(run())


# ---------------------------------------------------------------------------
# Optional parity plumbing
# ---------------------------------------------------------------------------

# Some parts of Thomas dynamically discover commands by looking for `COMMAND`
# metadata. We expose a minimal, dependency-free spec that can be consumed by
# such registries without importing argparse internals.

COMMAND: dict[str, Any] = {
    "name": COMMAND_NAME,
    "runner": run,
    "help": "Resolve which assistant should handle an inbound message.",
}
