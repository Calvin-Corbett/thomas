"""CLI wiring for invoking a named action on a node.

This command is intentionally thin: it validates/normalises CLI input, calls the
Thomas-native node action invocation helper, and prints either human-friendly text
or machine-readable JSON.

The surrounding Thomas CLI framework may register commands in different ways.
To stay compatible with common patterns in this codebase, this module exposes
multiple entrypoints (register/build_parser/add_parser) that all delegate to an
argparse-based implementation. Tests can call ``main([...])`` directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping, Optional, Sequence

from thomas.nodes.p039_nodes_invoke_action import (
    InvalidInvokeActionInput,
    InvokeActionRequest,
    NodeInvokeActionError,
    error_to_payload,
    invoke_action,
    response_to_payload,
)


def _parse_json_payload(payload_text: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(payload_text)
    except Exception as exc:
        raise InvalidInvokeActionInput(
            "payload must be valid JSON",
            details={"error": exc.__class__.__name__},
        ) from exc

    if parsed is None:
        return {}

    if not isinstance(parsed, dict):
        raise InvalidInvokeActionInput("payload must be a JSON object")

    return parsed


def _add_invoke_action_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--node",
        required=True,
        help="Node id (resolved via registry) or an http(s) URL",
    )
    parser.add_argument(
        "--action",
        required=True,
        help="Action name to invoke on the node",
    )
    parser.add_argument(
        "--payload",
        default="{}",
        help='JSON object passed to the action (default: "{}")',
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        dest="timeout_s",
        help="Request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON",
    )


def run(args: argparse.Namespace) -> int:
    """Execute the command and return an exit code."""

    node = str(getattr(args, "node", "") or "")
    action = str(getattr(args, "action", "") or "")
    timeout_s = float(getattr(args, "timeout_s", 30.0) or 30.0)
    json_output = bool(getattr(args, "json_output", False))

    try:
        payload_text = str(getattr(args, "payload", "{}") or "{}")
        payload = _parse_json_payload(payload_text)
        req = InvokeActionRequest(node=node, action=action, payload=payload, timeout_s=timeout_s)
        resp = invoke_action(req)
    except NodeInvokeActionError as exc:
        if json_output:
            print(json.dumps(error_to_payload(exc, node=node, action=action), ensure_ascii=False))
        else:
            print("ERROR[{code}]: {msg}".format(code=exc.code, msg=str(exc)), file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(response_to_payload(resp), ensure_ascii=False))
    else:
        print(
            "Invoked '{action}' on '{node}' (status {status})".format(
                action=resp.action, node=resp.node, status=resp.status_code
            )
        )
        if resp.result is not None:
            print(json.dumps(resp.result, indent=2, ensure_ascii=False))

    return 0


def register(subparsers: Any) -> None:
    """Register this command with an argparse-style subparser collection."""

    parser = subparsers.add_parser(
        "invoke-action",
        help="Invoke a named action on a node",
        description="Invoke a named action on a node",
    )
    _add_invoke_action_args(parser)
    parser.set_defaults(func=run)


# Common aliases used by various command discovery mechanisms.
build_parser = register
add_parser = register


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Standalone entrypoint (primarily for tests)."""

    argv = list(argv or sys.argv[1:])
    parser = argparse.ArgumentParser(prog="thomas nodes invoke-action")
    _add_invoke_action_args(parser)
    ns = parser.parse_args(argv)
    return run(ns)


# Metadata used by Thomas' command discovery/parity tooling (when available).
COMMAND_GROUP = "nodes"
COMMAND_NAME = "invoke-action"
COMMAND_HELP = "Invoke a named action on a node"
COMMAND_ALIASES = ("invoke_action", "invoke")


class _CommandSpec:
    """A tiny, framework-agnostic command descriptor."""

    group = COMMAND_GROUP
    name = COMMAND_NAME
    help = COMMAND_HELP
    aliases = COMMAND_ALIASES

    def __call__(self, subparsers: Any) -> None:  # pragma: no cover
        register(subparsers)


COMMAND = _CommandSpec()
COMMANDS = (COMMAND,)


def get_commands() -> Sequence[Any]:  # pragma: no cover
    return list(COMMANDS)
