from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

_COMMAND_NAME = "p013-browser-telemetry-console-stream"

COMMAND_NAME = _COMMAND_NAME
COMMAND_HELP = "Stream console messages from a live browser session."
COMMAND_DESCRIPTION = "Stream console messages from a live browser session (bounded by duration and max events)."


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    help: str
    description: str
    register: Callable[[Any], argparse.ArgumentParser | None]
    run: Callable[[argparse.Namespace], int]


def register(parent: Any) -> argparse.ArgumentParser | None:
    """Register this command with Thomas' CLI.

    Designed to be compatible with argparse-style subparser wiring.
    """
    add_parser = getattr(parent, "add_parser", None)
    if not callable(add_parser):
        return None

    parser = add_parser(_COMMAND_NAME, help=COMMAND_HELP, description=COMMAND_DESCRIPTION)
    _add_arguments(parser)
    parser.set_defaults(func=_run_from_args)
    return parser


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cdp-url", default=None, help="Chrome DevTools Protocol endpoint for the live browser.")
    parser.add_argument("--duration", type=float, default=5.0, help="How long to listen (seconds).")
    parser.add_argument("--max-events", type=int, default=250, help="Maximum console events to capture.")
    parser.add_argument("--poll", type=float, default=0.1, help="Polling interval used to pump events (seconds).")
    parser.add_argument(
        "--levels",
        default=None,
        help="Comma-separated console levels/types to include (e.g. error,warning,log). Default: all.",
    )
    parser.add_argument("--include-location", action="store_true", help="Include source location if available.")
    parser.add_argument("--include-args", action="store_true", help="Include console args (best-effort).")

    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON (single object) to stdout.")
    parser.add_argument(
        "--json-schema",
        action="store_true",
        help="Print the JSON schema for this command's output and exit.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Standalone entrypoint mainly for debugging."""
    parser = argparse.ArgumentParser(prog=_COMMAND_NAME, description=COMMAND_DESCRIPTION)
    _add_arguments(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return _run_from_args(args)


def _run_from_args(args: argparse.Namespace) -> int:
    # Late import to keep module import side-effect free.
    from thomas.browser.p013_browser_telemetry_console_stream import (
        BrowserConsoleStreamInput,
        BrowserTelemetryError,
        output_json_schema,
        stream_console,
    )

    if getattr(args, "json_schema", False):
        _print_json(output_json_schema())
        return 0

    levels = None
    if getattr(args, "levels", None):
        levels = [p.strip() for p in str(args.levels).split(",") if p.strip()]

    request = BrowserConsoleStreamInput(
        cdp_url=getattr(args, "cdp_url", None),
        duration_seconds=float(getattr(args, "duration", 5.0)),
        max_events=int(getattr(args, "max_events", 250)),
        poll_interval_seconds=float(getattr(args, "poll", 0.1)),
        levels=levels,
        include_location=bool(getattr(args, "include_location", False)),
        include_args=bool(getattr(args, "include_args", False)),
    )

    json_mode = bool(getattr(args, "json", False))

    try:
        if json_mode:
            out = stream_console(request)
            _print_json(out.to_dict())
        else:
            # Stream in human mode.
            def _printer(ev):
                loc = ""
                if ev.location and (ev.location.url or ev.location.line or ev.location.column):
                    loc = f" ({ev.location.url or ''}:{ev.location.line or ''}:{ev.location.column or ''})"
                sys.stdout.write(f"[{ev.level}] {ev.text}{loc}\n")
                sys.stdout.flush()

            stream_console(request, on_event=_printer)
        return 0
    except BrowserTelemetryError as exc:
        if json_mode:
            _print_json({"error": exc.to_dict()})
        else:
            sys.stderr.write(f"{exc.code}: {exc}\n")
            if getattr(exc, "details", None):
                sys.stderr.write(json.dumps(exc.details, ensure_ascii=False) + "\n")
        return 2
    except Exception as exc:
        if json_mode:
            _print_json({"error": {"code": "unexpected_error", "message": str(exc), "details": {}}})
        else:
            sys.stderr.write(f"unexpected_error: {exc}\n")
        return 3


def _print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


# A commonly-used integration pattern is to expose a top-level COMMAND object.
COMMAND = CommandSpec(
    name=COMMAND_NAME,
    help=COMMAND_HELP,
    description=COMMAND_DESCRIPTION,
    register=register,
    run=_run_from_args,
)

# Backwards/forwards compatibility aliases for different CLI wiring styles.
add_subparser = register
build_parser = register
add_to_subparsers = register


def run(args: argparse.Namespace) -> int:
    return _run_from_args(args)
