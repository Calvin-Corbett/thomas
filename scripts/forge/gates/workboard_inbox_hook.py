#!/usr/bin/env python3
"""Claude hook adapter for the workboard inbox hard gate."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crew.workboard import coordination_root
from scripts.forge.gates import workboard_inbox

# Same board as the gate this adapts: the primary checkout's, from any worktree.
DEFAULT_WORKBOARD = workboard_inbox.DEFAULT_WORKBOARD
# Command substitution executes arbitrary text that never contains a control
# operator, so it has to be rejected on its own terms.
_SUBSTITUTION = re.compile(r"\$\(|\$\{|`")
# Redirects that shape output without writing anywhere a caller can read back.
_INERT_REDIRECTS = ("2>&1", "2>/dev/null", "2>nul")
# Filters an agent pipes readonly output through. Nothing here can write a file
# or execute its input, which keeps the allowlist from being a bypass.
_READ_ONLY_FILTERS = frozenset({"head", "tail", "cat", "wc", "sort", "uniq", "grep", "findstr", "more", "less"})
_ALLOWED_SCRIPTS = (
    "scripts/crew/workboard/message.py",
    "scripts/forge/gates/workboard_inbox.py",
    "scripts/crew/brief/startup_router.py",
)
_ALLOWED_ACTIONS = ("--list", "--inbox", "--current", "--ack", "--resolve", "--sent")


def _normalized_command(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\\", "/")).strip()


_SINGLE = chr(39)
_DOUBLE = chr(34)
_BACKTICK = chr(96)


def _scan_command(command: str) -> tuple[list[str], bool]:
    """Split a command into pipeline segments, respecting quotes.

    Returns (segments, safe). safe is False when the command cannot be judged:
    unbalanced quotes, a redirect that writes somewhere, or shell substitution
    that would execute arbitrary text.

    This used to be a plain regex split on [;|]+|&&, which cannot tell a
    pipeline separator from the same character inside an argument. That refused
    an ordinary ack -- `... | grep -oE "acked|already"` was read as two
    segments, the second being `already"`, which matches no allowlist entry.
    A gate whose remediation command it rejects is the same deadlock this
    allowlist exists to prevent, one level down.

    Substitution is judged by quoting because the shell judges it that way:
    inside double quotes $(...) and backticks still expand, inside single
    quotes they are literal characters.
    """
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    index = 0
    length = len(command)
    while index < length:
        char = command[index]
        if char == _SINGLE and not in_double:
            in_single = not in_single
            current.append(char)
            index += 1
            continue
        if char == _DOUBLE and not in_single:
            in_double = not in_double
            current.append(char)
            index += 1
            continue
        if in_single:
            current.append(char)
            index += 1
            continue
        # unquoted, or inside double quotes where expansion still happens
        if char == _BACKTICK or command.startswith("$(", index) or command.startswith("${", index):
            return [], False
        if in_double:
            current.append(char)
            index += 1
            continue
        if char in "<>":
            rest = command[index:]
            previous = "".join(current).rstrip()
            inert = previous.endswith("2") and (
                rest.startswith(">&1") or rest.startswith(">/dev/null") or rest.startswith(">nul")
            )
            if not inert:
                return [], False
            # drop the redirect and the trailing 2 that introduced it
            while current and current[-1] != "2":
                current.pop()
            if current:
                current.pop()
            index += (
                len(">&1")
                if rest.startswith(">&1")
                else (len(">/dev/null") if rest.startswith(">/dev/null") else len(">nul"))
            )
            continue
        if char in ";|" or command.startswith("&&", index):
            segments.append("".join(current).strip())
            current = []
            index += 2 if command.startswith("&&", index) else 1
            while index < length and command[index] in ";|":
                index += 1
            continue
        current.append(char)
        index += 1
    if in_single or in_double:
        return [], False
    segments.append("".join(current).strip())
    return segments, True


def _is_allowlisted_tool_segment(segment: str) -> bool:
    if not any(script in segment for script in _ALLOWED_SCRIPTS):
        return False
    return any(action in segment.split() for action in _ALLOWED_ACTIONS)


def _is_read_only_filter_segment(segment: str) -> bool:
    tokens = segment.split()
    return bool(tokens) and tokens[0] in _READ_ONLY_FILTERS


def _is_single_inbox_command(command: str) -> bool:
    """Allow the gate's own remediation commands through the gate.

    The gate blocks Bash, and every command it tells the agent to run to clear
    the block is a Bash command. If this allowlist does not cover the shapes
    those are actually written in -- piped to `head`, `2>&1`, two acks chained
    with `;` -- the gate is a deadlock with no in-band exit.

    Widening it must not turn the allowlist into a bypass, so every segment of
    the pipeline has to independently be either an allowlisted inbox command or
    a filter that cannot write or execute anything.
    """
    normalized = _normalized_command(command)
    if not normalized:
        return False
    segments, safe = _scan_command(normalized)
    if not safe:
        return False
    if not all(segments):
        return False
    if not any(_is_allowlisted_tool_segment(segment) for segment in segments):
        return False
    return all(_is_allowlisted_tool_segment(segment) or _is_read_only_filter_segment(segment) for segment in segments)


def _hook_allows_ack(payload: dict[str, Any]) -> bool:
    tool_name = str(payload.get("tool_name") or "")
    if tool_name != "Bash":
        return False
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    return _is_single_inbox_command(command)


def evaluate_hook(
    *,
    hook_payload: dict[str, Any],
    workboard_path: Path = DEFAULT_WORKBOARD,
    agent: str = "",
) -> tuple[bool, str]:
    if _hook_allows_ack(hook_payload):
        return True, ""
    ok, payload = workboard_inbox.evaluate(workboard_path=workboard_path, agent=agent)
    if ok:
        return True, ""
    actor = str(payload.get("agent") or agent or "<unknown>")
    board = coordination_root.board_argument(workboard_path)
    unread = list(payload.get("unread_messages") or [])
    if unread:
        rows = [
            f"{row.get('msg_id')} from={row.get('from')} priority={row.get('priority')} summary={row.get('summary')}"
            for row in unread[:8]
            if isinstance(row, dict)
        ]
        detail = "\n".join(rows)
    else:
        detail = str(payload.get("error") or "inbox gate failed")
    return (
        False,
        "Unread Thomas workboard messages must be acked before this tool can run.\n"
        f"Agent: {actor}\n"
        f"{detail}\n"
        f"Run: python scripts/crew/workboard/message.py --inbox --agent {actor}{board}\n"
        f"Ack: python scripts/crew/workboard/message.py --ack --msg-id <msg-id> --agent {actor}{board}",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Claude PreToolUse adapter for Thomas workboard inbox gate.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--agent", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    raw = sys.stdin.read().strip()
    hook_payload: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                hook_payload = parsed
        except json.JSONDecodeError:
            hook_payload = {}
    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (workboard_inbox.ROOT / workboard_path).resolve()
    ok, message = evaluate_hook(hook_payload=hook_payload, workboard_path=workboard_path, agent=args.agent)
    if ok:
        return 0
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
