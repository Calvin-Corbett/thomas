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

from scripts.forge.gates import workboard_inbox

DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
_CONTROL_OPERATORS = ("&&", "||", ";", "\n", "\r", "|", ">", "<")


def _normalized_command(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\\", "/")).strip()


def _is_single_inbox_command(command: str) -> bool:
    normalized = _normalized_command(command)
    if not normalized:
        return False
    if any(op in normalized for op in _CONTROL_OPERATORS):
        return False
    allowed_scripts = (
        "scripts/crew/workboard/message.py",
        "scripts/forge/gates/workboard_inbox.py",
        "scripts/crew/brief/startup_router.py",
    )
    if not any(script in normalized for script in allowed_scripts):
        return False
    allowed_actions = ("--list", "--inbox", "--current", "--ack", "--resolve", "--sent")
    return any(action in normalized.split() for action in allowed_actions)


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
        f"Run: python scripts/crew/workboard/message.py --inbox --agent {actor}\n"
        f"Ack: python scripts/crew/workboard/message.py --ack --msg-id <msg-id> --agent {actor}",
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
        workboard_path = (ROOT / workboard_path).resolve()
    ok, message = evaluate_hook(hook_payload=hook_payload, workboard_path=workboard_path, agent=args.agent)
    if ok:
        return 0
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
