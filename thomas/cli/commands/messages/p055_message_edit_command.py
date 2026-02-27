"""CLI wiring for P055 - message edit command.

This module is intentionally Thomas-native while remaining compatible with the
CLI parity layer.

It exposes several entry points because different Thomas runners historically
look for different symbols:

- register(subparsers)
- build_parser(subparsers)  (alias)
- add_parser(subparsers)    (alias)
- handle(args, compat=None) (handler)
- main(argv=None)           (standalone)

Machine-readable output is supported via --json.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from thomas.messages.p055_message_edit_command import (
    ERR_INVALID_INPUT,
    MessageEditCommandError,
    MessageEditCommandInput,
    MessageEditCommandOutput,
    execute_message_edit,
)

PROMPT_ID = "P055"
COMMAND_GROUP = "messages"
COMMAND_NAME = "edit"


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `edit` subcommand under a messages group."""

    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Edit an existing message",
        description="Edit an existing message in a configured messaging channel.",
    )

    _add_arguments(parser)

    # Many Thomas CLI runners call args.func(args, compat)
    parser.set_defaults(func=handle)
    return parser


# Common aliases used by other runners
build_parser = register
add_parser = register


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    # Identifiers
    parser.add_argument(
        "message_id",
        nargs="?",
        help="Message identifier to edit (or provide via --message-id/--id)",
    )

    _safe_add_argument(
        parser,
        "--message-id",
        "--id",
        dest="message_id_flag",
        help="Message identifier to edit",
    )

    # New content
    parser.add_argument(
        "text",
        nargs="?",
        help="New message text (or provide via --text)",
    )

    _safe_add_argument(
        parser,
        "--text",
        "--content",
        dest="text_flag",
        help="New message text",
    )

    # Optional routing/context
    _safe_add_argument(
        parser,
        "--channel",
        "--channel-id",
        dest="channel_id",
        help="Channel identifier (optional; depends on adapter)",
    )

    # Optional metadata payload (JSON object)
    _safe_add_argument(
        parser,
        "--metadata",
        dest="metadata_json",
        help="Optional JSON object with provider-specific metadata",
    )

    # Output mode
    _safe_add_argument(
        parser,
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )


def handle(args: argparse.Namespace, compat: Any = None, *_: Any, **__: Any) -> int:
    """Execute message edit.

    Returns:
        Exit code (0 success, 1 failure)
    """

    json_mode = bool(getattr(args, "json", False))

    try:
        request = _args_to_request(args)
    except MessageEditCommandError as err:
        _emit_error(err, json_mode=json_mode)
        return 1

    editor = _resolve_editor(compat)

    try:
        result = execute_message_edit(request, editor=editor)
    except MessageEditCommandError as err:
        _emit_error(err, json_mode=json_mode)
        return 1

    _emit_success(result, json_mode=json_mode)
    return 0


def _args_to_request(args: argparse.Namespace) -> MessageEditCommandInput:
    message_id = (
        getattr(args, "message_id_flag", None) or getattr(args, "message_id", None) or getattr(args, "id", None) or ""
    )
    message_id = str(message_id).strip()

    text = getattr(args, "text_flag", None)
    if text is None:
        text = getattr(args, "text", None)
    if text is None:
        text = ""

    metadata: Any = None
    metadata_raw = getattr(args, "metadata_json", None)
    if metadata_raw:
        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            raise MessageEditCommandError(ERR_INVALID_INPUT, "metadata must be valid JSON.")
        if metadata is not None and not isinstance(metadata, dict):
            raise MessageEditCommandError(ERR_INVALID_INPUT, "metadata must be a JSON object.")

    return MessageEditCommandInput(
        message_id=message_id,
        new_text=str(text),
        channel_id=(getattr(args, "channel_id", None) or None),
        metadata=metadata,
    )


def _resolve_editor(compat: Any) -> Any:
    """Resolve an editor/client.

    Priority:
    1) Use compat passed in by the runner.
    2) Best-effort attempt to construct from thomas.cli.parity_compat (if available).

    If nothing can be resolved, return None and let the core command emit a
    deterministic missing_config error.
    """

    if compat is not None:
        return compat

    # Best-effort discovery: we keep this conservative and failure-safe.
    try:
        from thomas.cli import parity_compat  # type: ignore
    except ImportError:
        return None

    for fn_name in (
        "get_compat",
        "get_client",
        "get_default",
        "build_compat",
        "make_compat",
        "create_compat",
        "compat_from_env",
        "load_compat",
    ):
        fn = getattr(parity_compat, fn_name, None)
        if callable(fn):
            try:
                maybe = fn()
            except TypeError:
                continue
            except ImportError:
                return None
            if maybe is not None:
                return maybe

    return None


def _safe_add_argument(parser: argparse.ArgumentParser, *option_strings: str, **kwargs: Any) -> None:
    """Add an argparse option only if it is not already registered.

    Some Thomas CLI runners use a shared parent parser; re-adding common flags
    (like --json) would raise a conflict error.
    """

    existing = getattr(parser, "_option_string_actions", {})
    if any(opt in existing for opt in option_strings if opt.startswith("-")):
        return
    parser.add_argument(*option_strings, **kwargs)


def _emit_success(result: MessageEditCommandOutput, *, json_mode: bool) -> None:
    if json_mode:
        payload = {
            "ok": True,
            "result": result.to_dict(),
        }
        print(json.dumps(payload, sort_keys=True))
        return

    channel = f" in channel {result.channel_id}" if result.channel_id else ""
    print(f"Edited message {result.message_id}{channel}.")


def _emit_error(err: MessageEditCommandError, *, json_mode: bool) -> None:
    if json_mode:
        payload = {
            "ok": False,
            "error": err.to_dict(),
        }
        print(json.dumps(payload, sort_keys=True))
        return

    print(f"ERROR [{err.code}]: {err.message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point for debugging."""

    parser = argparse.ArgumentParser(prog="thomas messages edit")
    _add_arguments(parser)
    args = parser.parse_args(argv)
    return handle(args)


def __getattr__(name: str):  # pragma: no cover
    """Expose additional symbol names that different runners might expect."""

    if name in {"COMMAND", "command", "SPEC"}:
        return {
            "prompt_id": PROMPT_ID,
            "group": COMMAND_GROUP,
            "name": COMMAND_NAME,
            "register": register,
            "handler": handle,
            "help": "Edit an existing message",
        }

    if name in {"run_command", "run"}:
        return handle

    raise AttributeError(name)
