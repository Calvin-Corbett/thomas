#!/usr/bin/env python3
"""Bootstrap an agent session with a WIP workboard claim."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

try:
    from scripts import agent_identity
    from scripts import workboard_claim as claim_tool
except Exception:  # pragma: no cover
    import agent_identity  # type: ignore
    import workboard_claim as claim_tool  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"


def _resolve_agent(explicit_agent: str | None) -> str | None:
    return agent_identity.resolve_agent(explicit_agent, include_name_fallback=True)


def _detect_branch_name() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        branch = str(proc.stdout or "").strip()
    except Exception:
        branch = ""
    if branch and branch.upper() != "HEAD":
        return branch
    return "unknown-branch"


def _default_ticket() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"HSK-{stamp}"


def _build_task(task: str | None, ticket: str | None) -> str:
    base = str(task or "").strip()
    if not base:
        base = f"branch {_detect_branch_name()}"
    if base.startswith("[WIP]"):
        return base
    ticket_id = str(ticket or "").strip() or _default_ticket()
    return f"[WIP][{ticket_id}] {base}"


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a WIP claim for the current agent and print env exports."
    )
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    parser.add_argument(
        "--agent",
        default="",
        help=(
            "Agent id override (otherwise resolved from "
            f"{agent_identity.resolution_help(include_name_fallback=True)})."
        ),
    )
    parser.add_argument(
        "--scope",
        required=True,
        help="Claim scope path(s), comma-separated.",
    )
    parser.add_argument(
        "--task",
        default="",
        help="Task description. If omitted, defaults to current branch.",
    )
    parser.add_argument(
        "--ticket",
        default="",
        help="Handshake ticket id (default: generated HSK-YYYYMMDD-HHMMSS).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    agent = _resolve_agent(args.agent)
    if not agent:
        message = (
            "agent id is required; set THOMAS_AGENT_ID or AGENT_ID "
            "(CODEX_AGENT_ID/GEMINI_AGENT_ID/CLAUDE_AGENT_ID also supported) "
            "or pass --agent"
        )
        if args.json:
            payload = {
                "ok": False,
                "agent": "",
                "workboard": str(workboard_path),
                "error": message,
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Agent bootstrap claim: FAIL")
            print(f"- {message}")
        return 1

    task = _build_task(args.task, args.ticket)
    ok, message = claim_tool.claim(workboard_path, agent=agent, scope=args.scope, task=task)
    if not ok:
        if args.json:
            payload = {
                "ok": False,
                "agent": agent,
                "scope": args.scope,
                "task": task,
                "workboard": str(workboard_path),
                "error": message,
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Agent bootstrap claim: FAIL")
            print(f"- {message}")
        return 1

    ps_cmd = f'$env:AGENT_ID="{agent}"; $env:THOMAS_AGENT_ID="{agent}"'
    if args.json:
        payload = {
            "ok": True,
            "agent": agent,
            "scope": args.scope,
            "task": task,
            "workboard": str(workboard_path),
            "claim_result": message,
            "powershell_export": ps_cmd,
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Agent bootstrap claim: PASS")
        print(f"- agent: {agent}")
        print(f"- task: {task}")
        print(f"- {message}")
        print("- set explicit id for this shell:")
        print(f"  {ps_cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
