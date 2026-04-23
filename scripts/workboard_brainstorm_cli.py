#!/usr/bin/env python3
"""CLI entry points for workboard brainstorm sessions."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from scripts import workboard_brainstorm as brainstorm


def session_status(
    workboard_path: Path,
    *,
    session_id: str,
) -> tuple[bool, dict[str, object]]:
    session_clean = brainstorm._sanitize("session_id", session_id)
    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    sessions_section = brainstorm._find_section(lines, heading_prefix=brainstorm.SESSIONS_HEADING)
    notes_section = brainstorm._find_section(lines, heading_prefix=brainstorm.NOTES_HEADING)
    if sessions_section is None:
        return False, {"error": "missing `## Brainstorm Sessions` section"}
    sessions, session_errors = brainstorm._load_sessions(lines, sessions_section)
    if session_errors:
        return False, {"error": "brainstorm session parse failed", "violations": session_errors}
    notes: list[dict[str, str]] = []
    if notes_section is not None:
        notes, note_errors = brainstorm._load_notes(lines, notes_section)
        if note_errors:
            return False, {"error": "brainstorm notes parse failed", "violations": note_errors}
    row = brainstorm._session_lookup(sessions, session_clean)
    if row is None:
        return False, {"error": f"brainstorm session `{session_clean}` not found"}
    invited = brainstorm._agent_set(row.get("invited_agents", "none"))
    responded = brainstorm._agent_set(row.get("responded_agents", "none"))
    pending = sorted(invited - responded) if invited else []
    rows = [dict(item) for item in notes if brainstorm._norm(item.get("session_id", "")) == brainstorm._norm(session_clean)]
    return True, {
        "session": dict(row),
        "notes": rows,
        "note_count": len(rows),
        "pending_agents": pending,
        "pending_count": len(pending),
    }


def list_sessions(
    workboard_path: Path,
    *,
    state: str,
) -> tuple[bool, dict[str, object]]:
    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = brainstorm._find_section(lines, heading_prefix=brainstorm.SESSIONS_HEADING)
    if section is None:
        return True, {"sessions": [], "session_count": 0}
    rows, errors = brainstorm._load_sessions(lines, section)
    if errors:
        return False, {"error": "brainstorm session parse failed", "violations": errors}
    wanted = brainstorm._norm(state)
    out: list[dict[str, str]] = []
    for row in rows:
        if wanted and brainstorm._norm(row.get("state", "")) != wanted:
            continue
        out.append(dict(row))
    return True, {"sessions": out, "session_count": len(out)}


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage brainstorm sessions in WORKBOARD.md.")
    parser.add_argument("--workboard", default=str(brainstorm.DEFAULT_WORKBOARD))
    parser.add_argument("--json", action="store_true")

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--start", action="store_true")
    action.add_argument("--contribute", action="store_true")
    action.add_argument("--resolve-session", action="store_true")
    action.add_argument("--cancel-session", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--list", action="store_true")

    parser.add_argument("--session-id", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--objective", default="")
    parser.add_argument("--agent", default="")
    parser.add_argument("--initiator", default="")
    parser.add_argument("--facilitator", default=brainstorm.DEFAULT_FACILITATOR)
    parser.add_argument("--priority", default="p1")
    parser.add_argument("--kind", default="proposal")
    parser.add_argument("--all-hands", action="store_true")
    parser.add_argument("--invite-agents", default="")
    parser.add_argument("--dispatch-item", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-summons", action="store_true")
    parser.add_argument("--no-broadcast", action="store_true")
    parser.add_argument("--reason", default="")
    parser.add_argument("--state", default="")
    args = parser.parse_args(argv)

    workboard_path = brainstorm.resolve_workboard_path(args.workboard, repo_root=brainstorm.ROOT)
    if not workboard_path.exists():
        payload = {"ok": False, "error": f"missing workboard file: {workboard_path}"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard brainstorm tool: FAIL")
            print(f"- {payload['error']}")
        return 1

    try:
        if args.start:
            initiator = str(args.initiator or args.agent or args.facilitator or brainstorm.DEFAULT_FACILITATOR).strip()
            ok, payload = brainstorm.start_session(
                workboard_path,
                task_id=str(args.task_id).strip(),
                summary=str(args.summary).strip(),
                objective=str(args.objective).strip(),
                initiator=initiator,
                facilitator=str(args.facilitator).strip() or brainstorm.DEFAULT_FACILITATOR,
                all_hands=bool(args.all_hands),
                invite_agents=brainstorm._split_agents(str(args.invite_agents).strip()),
                priority=str(args.priority).strip(),
                send_summons=not bool(args.no_summons),
            )
            action_name = "start"
        elif args.contribute:
            actor = str(args.agent).strip()
            if not actor:
                raise ValueError("--agent is required for --contribute")
            ok, payload = brainstorm.contribute(
                workboard_path,
                session_id=str(args.session_id).strip(),
                agent=actor,
                kind=str(args.kind).strip(),
                summary=str(args.summary).strip(),
            )
            action_name = "contribute"
        elif args.resolve_session:
            ok, payload = brainstorm.resolve_session(
                workboard_path,
                session_id=str(args.session_id).strip(),
                facilitator=str(args.facilitator).strip() or brainstorm.DEFAULT_FACILITATOR,
                decision_summary=str(args.summary).strip(),
                dispatch_items=list(args.dispatch_item or []),
                force=bool(args.force),
                broadcast_decision=not bool(args.no_broadcast),
            )
            action_name = "resolve_session"
        elif args.cancel_session:
            ok, payload = brainstorm.cancel_session(
                workboard_path,
                session_id=str(args.session_id).strip(),
                facilitator=str(args.facilitator).strip() or brainstorm.DEFAULT_FACILITATOR,
                reason=str(args.reason).strip(),
            )
            action_name = "cancel_session"
        elif args.status:
            ok, payload = session_status(workboard_path, session_id=str(args.session_id).strip())
            action_name = "status"
        else:
            ok, payload = list_sessions(workboard_path, state=str(args.state).strip())
            action_name = "list"
    except ValueError as exc:
        ok = False
        payload = {"error": str(exc)}
        action_name = "error"

    envelope = {"ok": bool(ok), "action": action_name, "workboard": str(workboard_path), **payload}
    if args.json:
        print(json.dumps(envelope, sort_keys=True))
    else:
        print("Workboard brainstorm tool: PASS" if ok else "Workboard brainstorm tool: FAIL")
        if ok:
            if action_name == "list":
                for row in list(payload.get("sessions") or []):
                    print(f"- {row.get('session_id')}: {row.get('state')} [{row.get('priority')}] {row.get('summary')}")
            elif action_name == "status":
                row = dict(payload.get("session") or {})
                print(f"- {row.get('session_id')}: {row.get('state')} (pending={payload.get('pending_count', 0)})")
            else:
                session = dict(payload.get("session") or {})
                if session:
                    print(f"- {session.get('session_id')}: {session.get('state')}")
                else:
                    print(f"- action `{action_name}` completed")
        else:
            print(f"- {payload.get('error', 'unknown error')}")
            for item in list(payload.get("violations") or []):
                print(f"- {item}")
    return 0 if ok else 1
