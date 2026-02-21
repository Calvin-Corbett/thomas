"""CLI command for P053 - Message schema and persistence refactor.

This module is intentionally flexible about the surrounding CLI framework.

It exposes:
- `run(...)` returning a machine-readable dict
- `register(subparsers)` / `build_arg_parser(...)` for argparse-based CLIs
- optional click command (if click is installed)
- `COMMAND_SPEC` metadata for discovery

Key requirement: support `--json` output.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping, Optional

from thomas.messages.p053_message_schema_and_persistence_refactor import (
    MESSAGE_INGEST_JSON_SCHEMA,
    ThomasMessageError,
    ingest_and_persist_safe,
    list_messages_safe,
)

PROMPT_ID = "p053"

COMMAND_NAME = "p053-message-schema-and-persistence-refactor"
HELP = "Normalize and persist a message payload (schema v1)."


COMMAND_SPEC: dict[str, Any] = {
    "name": COMMAND_NAME,
    "help": HELP,
    "prompt_id": PROMPT_ID,
    "supports_json": True,
}


def command_spec() -> dict[str, Any]:
    return dict(COMMAND_SPEC)


def _read_json_arg(value: str) -> Any:
    """Parse JSON from a string or stdin when value is '-'"""
    if value == "-":
        value = sys.stdin.read()
    return json.loads(value)


def run(
    *,
    text: Optional[str] = None,
    channel: Optional[str] = None,
    sender: Optional[str] = None,
    metadata_json: Optional[str] = None,
    payload_json: Optional[str] = None,
    store_path: Optional[str] = None,
    list_limit: Optional[int] = None,
    list_channel: Optional[str] = None,
) -> dict[str, Any]:
    """Run the message ingest using either a full JSON payload or individual fields.

    If list_limit is provided, runs list mode instead of ingest mode.
    """
    if list_limit is not None:
        return list_messages_safe(store_path=store_path, limit=int(list_limit), channel=list_channel)

    if payload_json:
        try:
            payload = _read_json_arg(payload_json)
        except json.JSONDecodeError:
            return {"ok": False, "error": {"code": "invalid_input", "message": "payload must be valid JSON"}}
        if not isinstance(payload, Mapping):
            return {"ok": False, "error": {"code": "invalid_input", "message": "payload must be a JSON object"}}
        return ingest_and_persist_safe(payload, store_path=store_path)

    payload: dict[str, Any] = {}
    if text is not None:
        payload["text"] = text
    if channel is not None:
        payload["channel"] = channel
    if sender is not None:
        payload["sender"] = sender
    if metadata_json is not None:
        try:
            meta = _read_json_arg(metadata_json)
        except json.JSONDecodeError:
            return {"ok": False, "error": {"code": "invalid_input", "message": "metadata must be valid JSON"}}
        if not isinstance(meta, Mapping):
            return {"ok": False, "error": {"code": "invalid_input", "message": "metadata must be a JSON object"}}
        payload["metadata"] = dict(meta)

    return ingest_and_persist_safe(payload, store_path=store_path)


def build_arg_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(COMMAND_NAME, help=HELP)
    parser.add_argument("text", nargs="?", help="Message text")
    parser.add_argument("--channel", default=None)
    parser.add_argument("--sender", default=None)
    parser.add_argument("--metadata", dest="metadata_json", default=None, help="Metadata JSON object (or '-')")
    parser.add_argument("--payload", dest="payload_json", default=None, help="Full JSON payload (or '-')")
    parser.add_argument("--store", dest="store_path", default=None, help="Path to SQLite store")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Machine-readable output")

    parser.add_argument("--list", dest="list_limit", type=int, default=None, help="List last N messages instead of ingest")
    parser.add_argument("--list-channel", dest="list_channel", default=None, help="Filter list mode by channel")
    parser.add_argument("--print-schema", dest="print_schema", action="store_true", help="Print JSON request schema and exit")

    parser.set_defaults(_thomas_handler=_handle_args)
    return parser


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Alias for CLI discovery."""
    return build_arg_parser(subparsers)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Additional alias used by some Thomas CLI loaders."""
    return build_arg_parser(subparsers)


def _handle_args(args: argparse.Namespace) -> int:
    if bool(getattr(args, "print_schema", False)):
        sys.stdout.write(json.dumps(MESSAGE_INGEST_JSON_SCHEMA, sort_keys=True))
        sys.stdout.write("\n")
        return 0

    result = run(
        text=args.text,
        channel=args.channel,
        sender=args.sender,
        metadata_json=args.metadata_json,
        payload_json=args.payload_json,
        store_path=args.store_path,
        list_limit=args.list_limit,
        list_channel=args.list_channel,
    )

    json_output = bool(getattr(args, "json_output", False))
    if json_output:
        sys.stdout.write(json.dumps(result, sort_keys=True))
        sys.stdout.write("\n")
        return 0 if result.get("ok") else 2

    if result.get("ok") is True:
        # list mode
        if "messages" in result:
            sys.stdout.write(f"Listed {len(result.get('messages', []))} messages from {result.get('store_path')}\n")
            return 0
        msg = result.get("message", {})
        sys.stdout.write(f"Stored {msg.get('message_id')} in {result.get('store_path')}\n")
        return 0

    err = result.get("error", {})
    sys.stderr.write(f"ERROR[{err.get('code')}]: {err.get('message')}\n")
    return 2


# Optional click integration (used only if the surrounding CLI is click-based)
try:  # pragma: no cover
    import click  # type: ignore
except Exception:  # pragma: no cover
    click = None  # type: ignore

if click:  # pragma: no cover

    @click.command(name=COMMAND_NAME, help=HELP)
    @click.argument("text", required=False)
    @click.option("--channel", default=None)
    @click.option("--sender", default=None)
    @click.option("--metadata", "metadata_json", default=None)
    @click.option("--payload", "payload_json", default=None)
    @click.option("--store", "store_path", default=None)
    @click.option("--json", "json_output", is_flag=True, default=False)
    @click.option("--list", "list_limit", type=int, default=None)
    @click.option("--list-channel", "list_channel", default=None)
    @click.option("--print-schema", "print_schema", is_flag=True, default=False)
    def cli(
        text: Optional[str],
        channel: Optional[str],
        sender: Optional[str],
        metadata_json: Optional[str],
        payload_json: Optional[str],
        store_path: Optional[str],
        json_output: bool,
        list_limit: Optional[int],
        list_channel: Optional[str],
        print_schema: bool,
    ) -> None:
        if print_schema:
            click.echo(json.dumps(MESSAGE_INGEST_JSON_SCHEMA, sort_keys=True))
            raise SystemExit(0)

        result = run(
            text=text,
            channel=channel,
            sender=sender,
            metadata_json=metadata_json,
            payload_json=payload_json,
            store_path=store_path,
            list_limit=list_limit,
            list_channel=list_channel,
        )
        if json_output:
            click.echo(json.dumps(result, sort_keys=True))
            raise SystemExit(0 if result.get("ok") else 2)

        if result.get("ok") is True:
            if "messages" in result:
                click.echo(f"Listed {len(result.get('messages', []))} messages from {result.get('store_path')}")
                raise SystemExit(0)
            msg = result.get("message", {})
            click.echo(f"Stored {msg.get('message_id')} in {result.get('store_path')}")
            raise SystemExit(0)

        err = result.get("error", {})
        click.echo(f"ERROR[{err.get('code')}]: {err.get('message')}", err=True)
        raise SystemExit(2)


# Export a best-effort command handle for frameworks that expect it.
COMMAND = cli if click else None  # type: ignore


def main(argv: Optional[list[str]] = None) -> int:
    """Minimal module entrypoint for ad-hoc usage.

    Example:
      python -m thomas.cli.commands.messages.p053_message_schema_and_persistence_refactor \
        p053-message-schema-and-persistence-refactor --json --store ./messages.sqlite3 "hi"
    """
    parser = argparse.ArgumentParser(prog=COMMAND_NAME)
    subparsers = parser.add_subparsers(dest="cmd")
    build_arg_parser(subparsers)
    args = parser.parse_args(argv)
    handler = getattr(args, "_thomas_handler", None)
    if not handler:
        parser.print_help()
        return 0
    return int(handler(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
