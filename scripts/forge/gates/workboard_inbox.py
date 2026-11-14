#!/usr/bin/env python3
"""Unread workboard messages gate STARTING work, never finishing it.

``workboard_inbox_hook.py`` is the PreToolUse adapter and it still blocks Bash:
an agent cannot begin work without reading its mail, which is the point of the
rule. This module is the same check in the commit path, and there it runs
``--advisory``: it prints the unread messages and lets the commit through.

WHY: blocking a commit adds no protection and creates a treadmill. By commit time
the Bash gate has already forced the agent to read its inbox, so a message that
arrives during a gate run -- around forty seconds -- cannot concern work that is
already done; it can only strand it. Measured 2026-09-09 with four agents live: a
coordination message landed DURING the very gate run it then blocked, repeatedly,
and acked messages were still reported unread because acks live in WORKBOARD.md
and pre-commit stashes it, so the gate read HEAD's copy. At a hundred agents that
is permanent gridlock -- any agent could stop every other agent from committing
by sending a message.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.workboard import coordination_root
from scripts.crew.workboard import message as message_tool

# The board this gate judges is the board the message tool delivers to: the
# primary checkout's, for every linked worktree alike. Anchoring here to this
# script copy's own tree gated a worktree on a board nobody sent to.
ROOT = coordination_root.coordination_root()
DEFAULT_WORKBOARD = coordination_root.default_workboard(ROOT)


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
    try:
        workboard_path = Path(workboard_path).resolve()
    except OSError:
        workboard_path = Path(workboard_path)
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
            "Read and ack inbox: python scripts/crew/workboard/message.py --inbox "
            f"--agent {actor}{coordination_root.board_argument(workboard_path)}"
            if unread
            else ""
        ),
    }


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Require unread workboard messages to be acked before agent action.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--agent", default="")
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="Report unread messages without blocking. Used in the commit path.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    ok, payload = evaluate(workboard_path=workboard_path, agent=args.agent)
    advisory = bool(args.advisory)
    if args.json:
        payload = {**payload, "advisory": advisory}
        print(json.dumps(payload, sort_keys=True))
        return 0 if (ok or advisory) else 1

    if ok:
        print("Workboard inbox gate: PASS")
    else:
        print("Workboard inbox gate: ADVISORY" if advisory else "Workboard inbox gate: FAIL")
    if ok:
        print(f"- agent `{payload.get('agent', '')}` has no unread workboard messages")
        return 0

    if advisory:
        print("- reported, not blocking: unread mail gates starting work, not finishing it")
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
    return 0 if advisory else 1


if __name__ == "__main__":
    raise SystemExit(run())
