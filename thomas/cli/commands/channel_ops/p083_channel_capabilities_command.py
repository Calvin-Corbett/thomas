from __future__ import annotations

import json
import sys
from typing import Any

from thomas.channels.p083_channel_capabilities_command import (
    ChannelCapabilitiesCommandError,
    ChannelCapabilitiesRequest,
    get_channel_capabilities,
)

COMMAND_NAME = "capabilities"
HELP = "Show what a configured messaging channel can do"

COMMAND = {"name": COMMAND_NAME, "help": HELP}


def get_command() -> dict:
    return dict(COMMAND)


def register(subparsers: Any) -> Any:
    parser = subparsers.add_parser(COMMAND_NAME, help=HELP, description=HELP)
    parser.add_argument("channel", help="Configured channel name (from your Thomas config)")
    _maybe_add_json_flag(parser)
    _attach_handler(parser)
    return parser


add_parser = register
register_command = register


def run(args: Any, config: Any | None = None) -> int:
    channel_ref = getattr(args, "channel", None) or getattr(args, "name", None)
    json_mode = bool(getattr(args, "json", False))

    if config is None:
        config = (
            getattr(args, "config", None) or getattr(args, "thomas_config", None) or getattr(args, "app_config", None)
        )

    try:
        res = get_channel_capabilities(ChannelCapabilitiesRequest(channel=str(channel_ref)), config=config)
    except ChannelCapabilitiesCommandError as e:
        _emit_error(e, json_mode=json_mode)
        return 2

    if json_mode:
        print(json.dumps(res.to_dict(ok=True), sort_keys=True))
        return 0

    for line in res.to_human_lines():
        print(line)
    return 0


def _maybe_add_json_flag(parser: Any) -> None:
    try:
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    except json.JSONDecodeError:
        return


def _attach_handler(parser: Any) -> None:
    try:
        parser.set_defaults(func=run)
    except json.JSONDecodeError:
        pass
    try:
        parser.set_defaults(handler=run)
    except (ValueError, TypeError):
        pass


def _emit_error(err: ChannelCapabilitiesCommandError, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps({"ok": False, "error": err.to_dict()}, sort_keys=True))
        return

    print(f"ERROR[{err.code}]: {err.message}", file=sys.stderr)
    if err.details:
        print(f"Details: {err.details}", file=sys.stderr)
