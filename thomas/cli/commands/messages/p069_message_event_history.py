"""
CLI: message event history (P069)

This command is designed to be discoverable by the Thomas CLI parity layer.
It exposes both human output and `--json` output suitable for automation.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from thomas.messages.p069_message_event_history import (
    MessageEventHistoryConfigError,
    MessageEventHistoryError,
    MessageEventHistoryInvalidInputError,
    MessageEventHistoryRequest,
    get_message_event_history,
    response_to_json,
)


COMMAND_NAME = "message-event-history"
COMMAND_ALIASES = ["message_event_history", "event-history", "event_history", "events-history", "events_history"]
COMMAND_HELP = "Show recorded event history for a message id."


def build_parser(subparsers: Any, *, name: str = COMMAND_NAME) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        name,
        help=COMMAND_HELP,
        description=COMMAND_HELP,
        aliases=COMMAND_ALIASES,
    )
    parser.add_argument("message_id", help="Message identifier to query.")
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum number of events to return (default: 200, max: 2000).",
    )
    parser.add_argument(
        "--store",
        dest="store_path",
        default=None,
        help="Override the event store file path (defaults to configured store discovery).",
    )
    parser.add_argument(
        "--state-dir",
        dest="state_dir",
        default=None,
        help="Override the Thomas state directory used for store discovery.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.set_defaults(_thomas_cmd=run)
    return parser


def register(subparsers: Any) -> argparse.ArgumentParser:
    """Alias used by some CLI registries."""
    return build_parser(subparsers)


def _print_human(payload: dict[str, Any]) -> None:
    events = payload.get("events", [])
    if not events:
        print("No events found.")
        return

    print(f"Message: {payload.get('message_id')}")
    sources = payload.get("source_paths", [])
    if sources:
        print(f"Sources: {', '.join(sources)}")
    print("")

    print(f"{'occurred_at':<22}  {'event_type':<20}  {'source':<18}  raw")
    print("-" * 110)
    for ev in events:
        occurred = (ev.get("occurred_at") or "")[:22]
        etype = (ev.get("event_type") or "")[:20]
        source = (ev.get("source_path") or "")[-18:]
        raw = ev.get("raw")
        raw_compact = json.dumps(raw, ensure_ascii=False, sort_keys=True)
        print(f"{occurred:<22}  {etype:<20}  {source:<18}  {raw_compact}")


def run(args: argparse.Namespace) -> int:
    """Entry point used by argparse registries."""
    req = MessageEventHistoryRequest(
        message_id=getattr(args, "message_id", ""),
        limit=getattr(args, "limit", 200),
        store_path=getattr(args, "store_path", None),
        state_dir=getattr(args, "state_dir", None),
    )

    as_json = bool(getattr(args, "as_json", False))

    try:
        resp = get_message_event_history(req)
        payload = response_to_json(resp)
        if as_json:
            print(json.dumps({"ok": True, **payload}, ensure_ascii=False, sort_keys=True))
        else:
            _print_human(payload)
        return 0
    except MessageEventHistoryError as e:
        if as_json:
            print(json.dumps({"ok": False, "error": e.to_dict()}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR [{e.code}]: {e}")
        # Stable exit codes: invalid input -> 2, config -> 3, external -> 4
        if isinstance(e, MessageEventHistoryInvalidInputError):
            return 2
        if isinstance(e, MessageEventHistoryConfigError):
            return 3
        return 4
    except Exception as e:
        if as_json:
            print(
                json.dumps(
                    {"ok": False, "error": {"code": "messages.event_history.unknown", "message": repr(e)}},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(f"ERROR [messages.event_history.unknown]: {e!r}")
        return 1


# -----------------------------
# Compatibility surface
# -----------------------------


class _Command(dict):
    """Duck-typed command spec that works as both dict and attribute object.

    Some Thomas CLI registries treat commands as dicts, others as objects.
    We support both to reduce coupling.
    """

    def __init__(self, name: str, help_text: str):
        super().__init__(name=name, help=help_text, build_parser=build_parser, run=run)
        self.name = name
        self.help = help_text
        self.build_parser = build_parser
        self.run = run


COMMAND = _Command(COMMAND_NAME, COMMAND_HELP)
