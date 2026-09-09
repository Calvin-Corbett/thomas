#!/usr/bin/env python3
"""Block agent actions while the actor has unread workboard messages."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.workboard import message as message_tool

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"


def _message_summary(row: dict[str, object]) -> dict[str, str]:
    return {
        "msg_id": str(row.get("msg_id") or ""),
        "from": str(row.get("from") or ""),
        "priority": str(row.get("priority") or ""),
        "kind": str(row.get("kind") or ""),
        "summary": str(row.get("summary") or ""),
        "requested_action": str(row.get("requested_action") or ""),
        "escalation": str(row.get("escalation") or ""),
    }


def evaluate(
    *,
    workboard_path: Path = DEFAULT_WORKBOARD,
    agent: str = "",
) -> tuple[bool, dict[str, object]]:
    actor = message_tool.resolve_current_agent(agent)
    if not actor:
        return False, {
            "gate": "workboard_inbox",
            "ok": False,
            "error": "agent identity is required; pass --agent or set AGENT_ID/THOMAS_AGENT_ID",
            "workboard": str(workboard_path),
            "agent": "",
            "unread_count": 0,
            "unread_messages": [],
        }

    ok, payload = message_tool.unread_messages(workboard_path, agent=actor)
    if not ok:
        return False, {
            "gate": "workboard_inbox",
            "ok": False,
            "error": str(payload.get("error") or "message inbox check failed"),
            "workboard": str(workboard_path),
            "agent": actor,
            "unread_count": 0,
            "unread_messages": [],
            "violations": list(payload.get("violations") or []),
        }

    unread = [_message_summary(dict(row)) for row in list(payload.get("messages") or [])]
    return not bool(unread), {
        "gate": "workboard_inbox",
        "ok": not bool(unread),
        "workboard": str(workboard_path),
        "agent": actor,
        "unread_count": len(unread),
        "unread_messages": unread,
        "next_step": (
            f"Read and ack inbox: python scripts/crew/workboard/message.py --inbox --agent {actor}" if unread else ""
        ),
    }


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Require unread workboard messages to be acked before agent action.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--agent", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    ok, payload = evaluate(workboard_path=workboard_path, agent=args.agent)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return 0 if ok else 1

    print("Workboard inbox gate: PASS" if ok else "Workboard inbox gate: FAIL")
    if ok:
        print(f"- agent `{payload.get('agent', '')}` has no unread workboard messages")
        return 0

    print(f"- {payload.get('error', 'unread workboard messages must be acked before action')}")
    if payload.get("next_step"):
        print(f"- next: {payload['next_step']}")
    for row in list(payload.get("unread_messages") or []):
        escalation = str(row.get("escalation") or "")
        suffix = " ESCALATED" if escalation else ""
        print(
            f"- {row.get('msg_id')}: from={row.get('from')} priority={row.get('priority')}{suffix} "
            f"summary={row.get('summary')}"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
