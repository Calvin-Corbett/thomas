"""Enforce core event-contract parity across server, web UI, and CLI surfaces.

This is a static guard to catch drift when new events are added on one surface
but not wired through the others.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_EVENT_SOURCES: Sequence[Path] = (
    ROOT / "thomas" / "server" / "routes" / "chat_stream_events.py",
    ROOT / "thomas" / "server" / "routes" / "chat_request_execution.py",
    ROOT / "thomas" / "server" / "chat_control_mode.py",
)
WEB_RUNTIME_DIR = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
WEB_CHAT = ROOT / "thomas" / "server" / "web" / "js" / "chat.js"
WEB_APP = ROOT / "thomas" / "server" / "web" / "js" / "app.js"
WEB_APP_PARTS_DIR = ROOT / "thomas" / "server" / "web" / "js" / "app_parts"
CLI_EVENT_SOURCES: Sequence[Path] = (
    ROOT / "thomas" / "cli" / "_commands_base.py",
    ROOT / "thomas" / "cli" / "repl_agent_runtime.py",
)

REQUIRED_WIRE_EVENTS: set[str] = {
    "route",
    "text",
    "iteration",
    "tool_start",
    "tool_args",
    "tool_result",
    "guardrails",
    "error",
    "done",
}

REQUIRED_CLI_EVENTS: set[str] = {
    "AGENT_START",
    "TEXT_DELTA",
    "AGENT_ITERATION",
    "TOOL_CALL_START",
    "TOOL_CALL_ARGS_DELTA",
    "TOOL_RESULT",
    "AGENT_ERROR",
    "AGENT_DONE",
}

SERVER_STREAM_CONTEXT_PATTERN = re.compile(
    r"\b(?:send|json\.dumps|resp\.write|_record_swarm_event)\s*\(",
    re.IGNORECASE,
)
SERVER_STREAM_TYPE_LITERAL_PATTERN = re.compile(
    r"['\"]type['\"]\s*:\s*['\"]([a-z0-9_]+)['\"]",
    re.IGNORECASE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_server_sources() -> str:
    sources = [path for path in SERVER_EVENT_SOURCES if path.exists()]
    if not sources:
        expected = ", ".join(str(path) for path in SERVER_EVENT_SOURCES)
        raise FileNotFoundError(f"No server event source found. Expected one of: {expected}")
    return "\n".join(_read(path) for path in sources)


def _read_cli_sources() -> str:
    sources = [path for path in CLI_EVENT_SOURCES if path.exists()]
    if not sources:
        expected = ", ".join(str(path) for path in CLI_EVENT_SOURCES)
        raise FileNotFoundError(f"No CLI event source found. Expected one of: {expected}")
    return "\n".join(_read(path) for path in sources)


def _read_web_sources() -> str:
    """Read web chat sources from the live split runtime, with legacy fallback for tests."""
    sources: list[Path] = []
    if WEB_RUNTIME_DIR.exists():
        sources.extend(sorted(WEB_RUNTIME_DIR.glob("*.js")))
    else:
        if WEB_CHAT.exists():
            sources.append(WEB_CHAT)
        if WEB_APP.exists():
            sources.append(WEB_APP)
        if WEB_APP_PARTS_DIR.exists():
            sources.extend(sorted(WEB_APP_PARTS_DIR.glob("*.js")))

    if not sources:
        raise FileNotFoundError(
            "No web chat source found. Expected one of: "
            f"{WEB_RUNTIME_DIR}/*.js, {WEB_CHAT}, {WEB_APP}, {WEB_APP_PARTS_DIR}/*.js"
        )

    return "\n".join(_read(path) for path in sources)


def _slice_between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    if j < 0:
        return text[i:]
    return text[i:j]


def _extract_server_wire_events(server_text: str) -> set[str]:
    # Extract from stream emitters across route/helper files.
    events: set[str] = set()
    for context_match in SERVER_STREAM_CONTEXT_PATTERN.finditer(server_text):
        call_source = _extract_call_source(server_text, context_match.start())
        for event_type in SERVER_STREAM_TYPE_LITERAL_PATTERN.findall(call_source):
            events.add(event_type)
    return events


def _extract_call_source(text: str, context_start: int, max_chars: int = 8000) -> str:
    open_paren = text.find("(", context_start)
    if open_paren < 0:
        return ""

    in_single = False
    in_double = False
    escaped = False
    depth = 0
    end = min(len(text), open_paren + max_chars)

    for idx in range(open_paren, end):
        ch = text[idx]

        if in_single:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                in_single = False
            continue

        if in_double:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
            continue

        if ch == "'":
            in_single = True
            continue
        if ch == '"':
            in_double = True
            continue
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren : idx + 1]

    return text[open_paren:end]


def _extract_web_wire_handlers(web_text: str) -> set[str]:
    found = re.findall(r"(?:event|evt)\.type\s*===?\s*['\"]([a-z_]+)['\"]", web_text)
    return set(found)


def _extract_cli_event_handlers(cli_text: str) -> set[str]:
    # Focus on direct EventType checks in _run_chat.
    block = _slice_between(cli_text, "async def _run_chat(", "@click.group")
    # Fallback to whole source when the expected function window moves.
    haystack = block or cli_text
    found = re.findall(r"(?:event|evt)\.type\s*==\s*EventType\.([A-Z_]+)", haystack)
    return set(found)


def _missing(required: Iterable[str], actual: Iterable[str]) -> set[str]:
    return set(required) - set(actual)


def _print_missing(title: str, missing: set[str]) -> None:
    print(title)
    for item in sorted(missing):
        print(f"  - {item}")


def run() -> int:
    parser = argparse.ArgumentParser(description="Check Thomas surface event-contract parity.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args()

    server_text = _read_server_sources()
    web_text = _read_web_sources()
    cli_text = _read_cli_sources()

    server_events = _extract_server_wire_events(server_text)
    web_events = _extract_web_wire_handlers(web_text)
    cli_events = _extract_cli_event_handlers(cli_text)

    missing_server_required = _missing(REQUIRED_WIRE_EVENTS, server_events)
    missing_web_required = _missing(REQUIRED_WIRE_EVENTS, web_events)
    missing_cli_required = _missing(REQUIRED_CLI_EVENTS, cli_events)
    server_not_handled_by_web = _missing(server_events, web_events)

    report = {
        "ok": not (
            missing_server_required or missing_web_required or missing_cli_required or server_not_handled_by_web
        ),
        "gate": "surface_parity",
        "missing_server_required": sorted(missing_server_required),
        "missing_web_required": sorted(missing_web_required),
        "missing_cli_required": sorted(missing_cli_required),
        "server_not_handled_by_web": sorted(server_not_handled_by_web),
        "server_event_count": len(server_events),
        "web_event_count": len(web_events),
        "cli_event_count": len(cli_events),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    if missing_server_required:
        _print_missing("Missing required wire events in server stream mapping:", missing_server_required)
    if missing_web_required:
        _print_missing("Missing required wire event handlers in web chat:", missing_web_required)
    if missing_cli_required:
        _print_missing("Missing required core EventType handlers in CLI:", missing_cli_required)
    if server_not_handled_by_web:
        _print_missing("Server emits events not handled by web chat:", server_not_handled_by_web)

    if report["ok"]:
        print("Surface parity check: OK")
        print(f"  server wire events: {len(server_events)}")
        print(f"  web handlers: {len(web_events)}")
        print(f"  cli EventType handlers: {len(cli_events)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
