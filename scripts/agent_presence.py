#!/usr/bin/env python3
"""Repo-scoped agent presence CLI."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from thomas.core import agent_presence

ROOT = Path(__file__).resolve().parent.parent


def _format_status(payload: dict[str, object]) -> str:
    agents = list(payload.get("agents") or [])
    groups = {
        "registered active": [
            row
            for row in agents
            if str((row or {}).get("state") or "") in {"active", "alive"}
            and str((row or {}).get("confidence") or "") in {"high", "medium"}
        ],
        "registered declared": [
            row
            for row in agents
            if str((row or {}).get("state") or "") == "declared"
            and str((row or {}).get("confidence") or "") in {"high", "medium"}
        ],
        "registered stale": [
            row
            for row in agents
            if str((row or {}).get("state") or "") == "stale"
            and str((row or {}).get("confidence") or "") in {"high", "medium"}
        ],
        "heuristic/unregistered": [row for row in agents if str((row or {}).get("state") or "") == "unregistered"],
    }
    lines = [f"repo: {payload.get('repo_root')}", f"generated_at: {payload.get('generated_at')}"]
    for label, rows in groups.items():
        lines.append(f"{label}: {len(rows)}")
        for row in rows[:8]:
            item = dict(row or {})
            scope = ", ".join(list(item.get("scope") or [])[:3]) or "(none)"
            paths = ", ".join(list(item.get("recent_paths") or [])[:3]) or "(none)"
            task = str(item.get("task_summary") or "").strip() or "(no task)"
            evidence = "; ".join(list(item.get("evidence") or [])[:2]) or ""
            lines.append(
                f"- {item.get('display_name') or item.get('agent_id')} "
                f"state={item.get('state')} confidence={item.get('confidence')} scope={scope} recent_paths={paths}"
            )
            lines.append(f"  task={task}")
            if evidence:
                lines.append(f"  evidence={evidence}")
    services = list(payload.get("services") or [])
    lines.append(f"services: {len(services)}")
    for row in services[:5]:
        item = dict(row or {})
        commands = "; ".join(list(item.get("commands") or [])[:2]) or "(none)"
        lines.append(
            f"- {item.get('display_name')} pids={','.join(list(item.get('pids') or [])[:4])} commands={commands}"
        )
    inferred_candidates = list(payload.get("inferred_candidates") or [])
    inferred_applied = list(payload.get("inferred_applied") or [])
    inferred_suppressed = list(payload.get("inferred_suppressed") or [])
    inferred_expired = list(payload.get("inferred_expired") or [])
    lines.append(f"inferred candidates: {len(inferred_candidates)}")
    for row in inferred_candidates[:5]:
        item = dict(row or {})
        paths = ", ".join(list(item.get("recent_paths") or [])[:3]) or "(none)"
        lines.append(
            f"- {item.get('agent_id')} scope={item.get('scope')} confidence={item.get('confidence')} paths={paths}"
        )
    lines.append(f"inferred applied: {len(inferred_applied)}")
    for row in inferred_applied[:5]:
        item = dict(row or {})
        lines.append(f"- {item.get('agent_id')} scope={item.get('scope')} action={item.get('action')}")
    lines.append(f"inferred suppressed: {len(inferred_suppressed)}")
    for row in inferred_suppressed[:5]:
        item = dict(row or {})
        lines.append(f"- {item.get('scope')} reason={item.get('reason')}")
    lines.append(f"inferred expired: {len(inferred_expired)}")
    for row in inferred_expired[:5]:
        item = dict(row or {})
        lines.append(f"- {item.get('agent_id')} scope={item.get('scope')} state={item.get('state')}")
    warnings = list(payload.get("warnings") or [])
    conflicts = list(payload.get("conflicts") or [])
    lines.append(f"warnings: {len(warnings)}")
    for row in warnings[:5]:
        item = dict(row or {})
        lines.append(f"- {item.get('message')}")
    lines.append(f"conflicts: {len(conflicts)}")
    for row in conflicts[:5]:
        item = dict(row or {})
        lines.append(f"- {item.get('message')}")
    return "\n".join(lines)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repo-scoped agent presence monitor.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    register = sub.add_parser("register", help="Register or refresh a presence session.")
    register.add_argument("--repo", default=str(ROOT))
    register.add_argument("--session-id", default="")
    register.add_argument("--agent", default="")
    register.add_argument("--display-name", default="")
    register.add_argument("--launcher", default="agent_presence")
    register.add_argument("--task", default="")
    register.add_argument("--scope", default="")
    register.add_argument("--claim-status", default="")
    register.add_argument("--json", action="store_true")

    heartbeat = sub.add_parser("heartbeat", help="Refresh an existing presence session.")
    heartbeat.add_argument("--repo", default=str(ROOT))
    heartbeat.add_argument("--session-id", default="")
    heartbeat.add_argument("--task", default=None)
    heartbeat.add_argument("--scope", default=None)
    heartbeat.add_argument("--claim-status", default=None)
    heartbeat.add_argument("--json", action="store_true")

    close = sub.add_parser("close", help="Close a presence session.")
    close.add_argument("--repo", default=str(ROOT))
    close.add_argument("--session-id", default="")
    close.add_argument("--state", default="closed")
    close.add_argument("--json", action="store_true")

    status = sub.add_parser("status", help="Show repo presence status.")
    status.add_argument("--repo", default=str(ROOT))
    status.add_argument("--workboard", default="")
    status.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()

    if args.cmd == "register":
        payload = agent_presence.register_session(
            repo_root=repo,
            session_id=str(args.session_id or "") or None,
            agent_id=str(args.agent or "") or None,
            display_name=str(args.display_name or "") or None,
            launcher=str(args.launcher or "agent_presence"),
            task_summary=str(args.task or ""),
            scope=str(args.scope or ""),
            claim_status=str(args.claim_status or ""),
            origin="agent_presence_cli",
        )
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"registered: {payload.get('session_id')} {payload.get('display_name') or payload.get('agent_id')}")
        return 0

    if args.cmd == "heartbeat":
        payload = agent_presence.heartbeat_session(
            repo_root=repo,
            session_id=str(args.session_id or "") or None,
            task_summary=args.task,
            scope=args.scope,
            claim_status=args.claim_status,
        )
        if payload is None:
            message = {"ok": False, "error": "session_not_found"}
            print(json.dumps(message, sort_keys=True) if args.json else "session not found")
            return 1
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"heartbeat: {payload.get('session_id')}")
        return 0

    if args.cmd == "close":
        ok = agent_presence.close_session(
            repo_root=repo, session_id=str(args.session_id or "") or None, state=str(args.state or "closed")
        )
        payload = {"ok": bool(ok), "session_id": str(args.session_id or agent_presence.current_session_id() or "")}
        print(json.dumps(payload, sort_keys=True) if args.json else ("closed" if ok else "session not found"))
        return 0 if ok else 1

    payload = agent_presence.collect_presence(repo_root=repo, workboard_path=str(args.workboard or "") or None)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(_format_status(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
