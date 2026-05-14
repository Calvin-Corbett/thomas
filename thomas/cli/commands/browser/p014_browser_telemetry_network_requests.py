from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any
from collections.abc import Callable, Sequence

_COMMAND_NAME = "p014-browser-telemetry-network-requests"

COMMAND_NAME = _COMMAND_NAME
COMMAND_HELP = "Capture network request telemetry from a live browser session."
COMMAND_DESCRIPTION = (
    "Capture network request telemetry from a live browser session (bounded by duration and max entries)."
)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    help: str
    description: str
    register: Callable[[Any], argparse.ArgumentParser | None]
    run: Callable[[argparse.Namespace], int]


def register(parent: Any) -> argparse.ArgumentParser | None:
    """Register this command with Thomas' CLI."""
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
    parser.add_argument("--max-entries", type=int, default=500, help="Maximum request entries to capture.")
    parser.add_argument("--poll", type=float, default=0.1, help="Polling interval used to pump events (seconds).")

    parser.add_argument("--include-headers", action="store_true", help="Include request headers (best-effort).")
    parser.add_argument("--include-post-data", action="store_true", help="Include request post body (best-effort).")
    parser.add_argument(
        "--include-response-headers", action="store_true", help="Include response headers (best-effort)."
    )

    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON (single object) to stdout.")
    parser.add_argument(
        "--json-schema",
        action="store_true",
        help="Print the JSON schema for this command's output and exit.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=_COMMAND_NAME, description=COMMAND_DESCRIPTION)
    _add_arguments(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return _run_from_args(args)


def _run_from_args(args: argparse.Namespace) -> int:
    from thomas.browser.p014_browser_telemetry_network_requests import (
        BrowserNetworkRequestsInput,
        BrowserTelemetryError,
        capture_network_requests,
        output_json_schema,
    )

    if getattr(args, "json_schema", False):
        _print_json(output_json_schema())
        return 0

    request = BrowserNetworkRequestsInput(
        cdp_url=getattr(args, "cdp_url", None),
        duration_seconds=float(getattr(args, "duration", 5.0)),
        max_entries=int(getattr(args, "max_entries", 500)),
        poll_interval_seconds=float(getattr(args, "poll", 0.1)),
        include_headers=bool(getattr(args, "include_headers", False)),
        include_post_data=bool(getattr(args, "include_post_data", False)),
        include_response_headers=bool(getattr(args, "include_response_headers", False)),
    )

    json_mode = bool(getattr(args, "json", False))

    try:
        if json_mode:
            out = capture_network_requests(request)
            _print_json(out.to_dict())
        else:
            def _printer(r):
                status = r.response_status if r.response_status is not None else "-"
                if r.failure_text:
                    status = "FAILED"
                sys.stdout.write(f"[{status}] {r.method} {r.url}\n")
                sys.stdout.flush()

            capture_network_requests(request, on_event=_printer)
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


COMMAND = CommandSpec(
    name=COMMAND_NAME,
    help=COMMAND_HELP,
    description=COMMAND_DESCRIPTION,
    register=register,
    run=_run_from_args,
)

add_subparser = register
build_parser = register
add_to_subparsers = register


def run(args: argparse.Namespace) -> int:
    return _run_from_args(args)
