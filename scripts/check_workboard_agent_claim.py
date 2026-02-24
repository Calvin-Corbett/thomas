#!/usr/bin/env python3
"""Require an active workboard claim for the current agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

try:
    from scripts import agent_identity
    from scripts import check_workboard_claims as claims_gate
except Exception:  # pragma: no cover
    import agent_identity  # type: ignore
    import check_workboard_claims as claims_gate  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"


def _resolve_agent(explicit_agent: str | None) -> str | None:
    return agent_identity.resolve_agent(explicit_agent, include_name_fallback=True)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Require an active WORKBOARD claim matching the current agent id."
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
                "gate": "workboard_agent_claim",
                "ok": False,
                "agent": "",
                "active_claim_count": 0,
                "workboard": str(workboard_path),
                "error": message,
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard agent claim gate: FAIL")
            print(f"- {message}")
        return 1

    violations, claims = claims_gate.evaluate_claims(workboard_path)
    if violations:
        if args.json:
            payload = {
                "gate": "workboard_agent_claim",
                "ok": False,
                "agent": agent,
                "active_claim_count": len(claims),
                "workboard": str(workboard_path),
                "error": "workboard claims invalid",
                "violations": list(violations),
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard agent claim gate: FAIL")
            for item in violations:
                print(f"- {item}")
        return 1

    normalized = str(agent).strip().lower()
    mine = [claim for claim in claims if str(claim.agent).strip().lower() == normalized]
    if not mine:
        message = (
            f"no active workboard claim found for '{agent}'. "
            "Run scripts/workboard_claim.py --claim before committing."
        )
        if args.json:
            payload = {
                "gate": "workboard_agent_claim",
                "ok": False,
                "agent": agent,
                "active_claim_count": len(claims),
                "matching_claim_count": 0,
                "workboard": str(workboard_path),
                "error": message,
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard agent claim gate: FAIL")
            print(f"- {message}")
        return 1

    scopes = sorted({scope for claim in mine for scope in claim.scopes})
    if args.json:
        payload = {
            "gate": "workboard_agent_claim",
            "ok": True,
            "agent": agent,
            "active_claim_count": len(claims),
            "matching_claim_count": len(mine),
            "scopes": scopes,
            "workboard": str(workboard_path),
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Workboard agent claim gate: PASS")
        print(f"- agent: {agent}")
        print(f"- matching claims: {len(mine)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
