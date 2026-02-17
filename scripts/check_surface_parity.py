"""Enforce core event-contract parity across server, web UI, and CLI surfaces.

This is a static guard to catch drift when new events are added on one surface
but not wired through the others.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence, Set


ROOT = Path(__file__).resolve().parent.parent
SERVER_APP = ROOT / "thomas" / "server" / "app.py"
WEB_CHAT = ROOT / "thomas" / "server" / "web" / "js" / "chat.js"
CLI_MAIN = ROOT / "thomas" / "cli" / "main.py"

REQUIRED_WIRE_EVENTS: Set[str] = {
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

REQUIRED_CLI_EVENTS: Set[str] = {
    "AGENT_START",
    "TEXT_DELTA",
    "AGENT_ITERATION",
    "TOOL_CALL_START",
    "TOOL_CALL_ARGS_DELTA",
    "TOOL_RESULT",
    "AGENT_ERROR",
    "AGENT_DONE",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _slice_between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    if j < 0:
        return text[i:]
    return text[i:j]


def _extract_server_wire_events(server_text: str) -> Set[str]:
    # Extract from calls like: await send({"type": "text", ...}) within api_chat.
    events: Set[str] = set()
    try:
        tree = ast.parse(server_text)
    except SyntaxError:
        return events

    api_chat_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "api_chat":
            api_chat_node = node
            break
    if api_chat_node is None:
        return events

    for node in ast.walk(api_chat_node):
        if not isinstance(node, ast.Call):
            continue
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        if func_name != "send" or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Dict):
            continue
        for k, v in zip(first.keys, first.values):
            if isinstance(k, ast.Constant) and k.value == "type":
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    events.add(v.value)
    return events


def _extract_web_wire_handlers(web_text: str) -> Set[str]:
    found = re.findall(r"event\.type\s*===\s*['\"]([a-z_]+)['\"]", web_text)
    return set(found)


def _extract_cli_event_handlers(cli_text: str) -> Set[str]:
    # Focus on direct EventType checks in _run_chat.
    block = _slice_between(cli_text, "async def _run_chat(", "@click.group")
    if not block:
        return set()
    found = re.findall(r"event\.type\s*==\s*EventType\.([A-Z_]+)", block)
    return set(found)


def _missing(required: Iterable[str], actual: Iterable[str]) -> Set[str]:
    return set(required) - set(actual)


def _print_missing(title: str, missing: Set[str]) -> None:
    print(title)
    for item in sorted(missing):
        print(f"  - {item}")


def run() -> int:
    parser = argparse.ArgumentParser(description="Check Thomas surface event-contract parity.")
    _ = parser.parse_args()

    server_text = _read(SERVER_APP)
    web_text = _read(WEB_CHAT)
    cli_text = _read(CLI_MAIN)

    server_events = _extract_server_wire_events(server_text)
    web_events = _extract_web_wire_handlers(web_text)
    cli_events = _extract_cli_event_handlers(cli_text)

    missing_server_required = _missing(REQUIRED_WIRE_EVENTS, server_events)
    missing_web_required = _missing(REQUIRED_WIRE_EVENTS, web_events)
    missing_cli_required = _missing(REQUIRED_CLI_EVENTS, cli_events)
    server_not_handled_by_web = _missing(server_events, web_events)

    failed = False
    if missing_server_required:
        _print_missing("Missing required wire events in server stream mapping:", missing_server_required)
        failed = True
    if missing_web_required:
        _print_missing("Missing required wire event handlers in web chat:", missing_web_required)
        failed = True
    if missing_cli_required:
        _print_missing("Missing required core EventType handlers in CLI:", missing_cli_required)
        failed = True
    if server_not_handled_by_web:
        _print_missing("Server emits events not handled by web chat:", server_not_handled_by_web)
        failed = True

    if failed:
        return 1

    print("Surface parity check: OK")
    print(f"  server wire events: {len(server_events)}")
    print(f"  web handlers: {len(web_events)}")
    print(f"  cli EventType handlers: {len(cli_events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
