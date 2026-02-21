from __future__ import annotations

"""
Thomas CLI – P146 Responses create stream events

This command is meant for parity testing and automation.

Modes:
- Local (default): generate deterministic events in-process.
- Remote (--base-url): POST to a running server and retrieve events using ?format=json.

Output:
- Default: prints SSE text (event/data format).
- --json: prints a JSON array of event objects.
"""

import argparse
import json
import sys
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from thomas.server.routes.gateway import p146_responses_create_stream_events as impl


COMMAND_NAME = "p146-responses-create-stream-events"
HELP = "Responses create stream events (P146)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=COMMAND_NAME, description=HELP)
    parser.add_argument("--model", default="gpt-5", help="Model name to include in the request payload.")
    parser.add_argument("--input", required=True, help="User input text (mapped to Responses API `input`).")
    parser.add_argument(
        "--base-url",
        default=None,
        help="If provided, POST to <base-url>/v1/responses?format=json and read the event list response.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout (list of event objects).")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout (seconds) for --base-url mode.")
    return parser


def _run_local(model: str, input_text: str) -> List[Dict[str, Any]]:
    payload = {"model": model, "input": input_text, "stream": True}
    parsed = impl.parse_create_response_request(payload)
    events = impl.build_stream_events(
        parsed,
        response_id="resp_cli",
        message_id="msg_cli",
        created_at=123,
        completed_at=124,
    )
    return events


def _run_remote(base_url: str, model: str, input_text: str, timeout_s: float) -> List[Dict[str, Any]]:
    url = base_url.rstrip("/") + "/v1/responses?format=json"
    payload = json.dumps({"model": model, "input": input_text, "stream": True}).encode("utf-8")

    req = Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    with urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        obj = json.loads(body)
        events = obj.get("events")
        if not isinstance(events, list):
            raise RuntimeError("Remote response did not contain an 'events' list.")
        return events


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.base_url:
            events = _run_remote(args.base_url, args.model, args.input, args.timeout)
        else:
            events = _run_local(args.model, args.input)

        if args.json:
            sys.stdout.write(json.dumps(events, ensure_ascii=False))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(impl.events_to_sse(events))
    except Exception as e:
        sys.stderr.write(json.dumps({"ok": False, "error": {"message": str(e), "code": "cli_error"}}) + "\n")
        return 2

    return 0


def register(subparsers: Any) -> None:
    sub = subparsers.add_parser(COMMAND_NAME, help=HELP)
    for action in build_parser()._actions:
        if not action.option_strings:
            continue
        if action.dest == "help":
            continue
        sub._add_action(action)
    sub.set_defaults(_thomas_entrypoint=main)


add_parser = register
