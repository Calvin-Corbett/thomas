#!/usr/bin/env python3
"""Require an active workboard claim and owned issue accountability."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
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


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    while "//" in path:
        path = path.replace("//", "/")
    return path.strip("/")


def _scope_matches_path(scope: str, rel_path: str) -> bool:
    scope_norm = _normalize_path(scope).lower()
    path_norm = _normalize_path(rel_path).lower()
    if not scope_norm or not path_norm:
        return False
    if scope_norm in {".", "*", "**"}:
        return True
    if any(ch in scope_norm for ch in "*?["):
        if fnmatch.fnmatchcase(path_norm, scope_norm):
            return True
        if scope_norm.endswith("/**"):
            base = scope_norm[:-3].rstrip("/")
            return bool(base) and (path_norm == base or path_norm.startswith(base + "/"))
        return False
    return path_norm == scope_norm or path_norm.startswith(scope_norm + "/")


def _staged_files() -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    rows: list[str] = []
    for raw in str(proc.stdout or "").splitlines():
        item = _normalize_path(raw)
        if item:
            rows.append(item)
    return sorted(set(rows))


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Require an active WORKBOARD claim matching the current agent id and no "
            "unresolved Issues / Blockers owned by that agent."
        )
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
        "--enforce-staged-scope",
        action="store_true",
        help=(
            "Require all staged files to be covered by the current agent's active "
            "claim scope."
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

    violations, claims, _tasks, _grab, issues = claims_gate.evaluate_board(workboard_path)
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

    normalized = _norm(agent)
    mine = [claim for claim in claims if _norm(claim.agent) == normalized]
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

    unresolved_owned = [
        issue
        for issue in issues
        if _norm(issue.owner) == normalized and _norm(issue.state) != "resolved"
    ]
    if unresolved_owned:
        issue_ids = [str(issue.issue_id).strip() for issue in unresolved_owned if str(issue.issue_id).strip()]
        issue_ids = sorted(set(issue_ids))
        issue_list = ", ".join(issue_ids) if issue_ids else "unknown issue ids"
        message = (
            f"agent '{agent}' owns unresolved workboard issue(s): {issue_list}. "
            "Resolve or reassign them before committing."
        )
        if args.json:
            payload = {
                "gate": "workboard_agent_claim",
                "ok": False,
                "agent": agent,
                "active_claim_count": len(claims),
                "matching_claim_count": len(mine),
                "unresolved_issue_count": len(unresolved_owned),
                "unresolved_issue_ids": issue_ids,
                "workboard": str(workboard_path),
                "error": message,
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard agent claim gate: FAIL")
            print(f"- {message}")
        return 1

    scopes = sorted({scope for claim in mine for scope in claim.scopes})
    staged_files: list[str] = []
    unclaimed_staged_files: list[str] = []
    if args.enforce_staged_scope:
        staged_files = _staged_files()
        for rel_path in staged_files:
            if not any(_scope_matches_path(scope, rel_path) for scope in scopes):
                unclaimed_staged_files.append(rel_path)
    if unclaimed_staged_files:
        message = (
            f"agent '{agent}' has staged files outside claimed scope. "
            "Update the WORKBOARD claim scope before committing."
        )
        if args.json:
            payload = {
                "gate": "workboard_agent_claim",
                "ok": False,
                "agent": agent,
                "active_claim_count": len(claims),
                "matching_claim_count": len(mine),
                "unresolved_issue_count": 0,
                "unresolved_issue_ids": [],
                "scopes": scopes,
                "workboard": str(workboard_path),
                "error": message,
                "enforce_staged_scope": True,
                "staged_file_count": len(staged_files),
                "staged_files_outside_scope_count": len(unclaimed_staged_files),
                "staged_files_outside_scope": unclaimed_staged_files,
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard agent claim gate: FAIL")
            print(f"- {message}")
            print("- claimed scopes:")
            for scope in scopes:
                print(f"  - {scope}")
            print("- staged files outside scope:")
            for path in unclaimed_staged_files:
                print(f"  - {path}")
        return 1
    if args.json:
        payload = {
            "gate": "workboard_agent_claim",
            "ok": True,
            "agent": agent,
            "active_claim_count": len(claims),
            "matching_claim_count": len(mine),
            "unresolved_issue_count": 0,
            "unresolved_issue_ids": [],
            "scopes": scopes,
            "enforce_staged_scope": bool(args.enforce_staged_scope),
            "staged_file_count": len(staged_files),
            "staged_files_outside_scope_count": 0,
            "staged_files_outside_scope": [],
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
