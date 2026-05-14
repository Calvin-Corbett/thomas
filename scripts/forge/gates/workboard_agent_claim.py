#!/usr/bin/env python3
"""Require an active workboard claim and owned issue accountability."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Ensure repo root is on sys.path so `from scripts import ...` works
# regardless of how pre-commit invokes this script.
_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from scripts import agent_identity
    from scripts.forge.gates import workboard_claims as claims_gate
    from scripts.crew.workboard import claim as workboard_claim_tool
except ImportError:  # pragma: no cover
    import agent_identity  # type: ignore
    from scripts.forge.gates import workboard_claims as claims_gate  # type: ignore
    from crew.workboard import claim as workboard_claim_tool  # type: ignore


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"


def _runtime_protection_disabled() -> bool:
    """Check if a human has temporarily disabled runtime protection."""
    return (ROOT / "runtime" / ".runtime_protection_disabled").is_file()


DEFAULT_STAGED_SCOPE_IGNORE: tuple[str, ...] = ("CHANGELOG.md", "pyproject.toml", "thomas/__init__.py")
FALLBACK_SCOPE_ENV = "THOMAS_WORKBOARD_SCOPE_FALLBACK"
FALLBACK_REASON_ENV = "THOMAS_WORKBOARD_SCOPE_FALLBACK_REASON"
SCOPE_SOURCE_CLAIM = "workboard_claim"
SCOPE_SOURCE_FALLBACK = "explicit_fallback"


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
    if path_norm == scope_norm or path_norm.startswith(scope_norm + "/"):
        return True
    if any(ch in scope_norm for ch in "*?["):
        if fnmatch.fnmatchcase(path_norm, scope_norm):
            return True
        if scope_norm.endswith("/**"):
            base = scope_norm[:-3].rstrip("/")
            return bool(base) and (path_norm == base or path_norm.startswith(base + "/"))
        return False
    return False


def _claim_role(claim: claims_gate.Claim) -> str:
    explicit = str(getattr(claim, "role", "") or "").strip().lower()
    if explicit:
        return explicit
    parent = str(getattr(claim, "parent", "") or "").strip()
    return "worker" if parent else "solo"


def _staged_files() -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    rows: list[str] = []
    for raw in str(proc.stdout or "").splitlines():
        item = _normalize_path(raw)
        if item:
            rows.append(item)
    return sorted(set(rows))


def _split_patterns(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        for token in str(raw or "").split(","):
            item = _normalize_path(token)
            if item:
                out.append(item)
    return sorted(set(out), key=str.lower)


def _git_status_porcelain() -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    rows: list[str] = []
    for raw in str(proc.stdout or "").splitlines():
        line = str(raw or "").rstrip()
        if line:
            rows.append(line)
    return rows


def _porcelain_path(line: str) -> str:
    raw = str(line or "")
    if len(raw) <= 3:
        return _normalize_path(raw)
    token = raw[3:].strip()
    if " -> " in token:
        token = token.split(" -> ", 1)[1].strip()
    return _normalize_path(token)


def _is_ignored_path(rel_path: str, ignore_patterns: Sequence[str]) -> bool:
    path = _normalize_path(rel_path)
    if not path:
        return True
    for pattern in ignore_patterns:
        pat = _normalize_path(pattern)
        if not pat:
            continue
        if _scope_matches_path(pat, path):
            return True
    return False


def _claimed_scope_dirty_paths(
    scopes: Sequence[str],
    *,
    enforce_untracked: bool = False,
    ignore_patterns: Sequence[str] = (),
) -> dict[str, list[str]]:
    unstaged: list[str] = []
    untracked: list[str] = []
    normalized_scopes = [scope for scope in scopes if _normalize_path(scope)]
    if not normalized_scopes:
        return {"unstaged": [], "untracked": []}

    for line in _git_status_porcelain():
        rel_path = _porcelain_path(line)
        if not rel_path:
            continue
        if _is_ignored_path(rel_path, ignore_patterns):
            continue
        if not any(_scope_matches_path(scope, rel_path) for scope in normalized_scopes):
            continue

        if line.startswith("??"):
            if enforce_untracked:
                untracked.append(rel_path)
            continue
        if line.startswith("!!"):
            continue

        worktree_status = line[1] if len(line) > 1 else " "
        if worktree_status not in (" ", "?", "!"):
            unstaged.append(rel_path)

    return {
        "unstaged": sorted(set(unstaged)),
        "untracked": sorted(set(untracked)),
    }


def _fallback_scopes_from_env() -> tuple[str, ...]:
    return tuple(_split_patterns([os.getenv(FALLBACK_SCOPE_ENV, "")]))


def _fallback_reason_from_env() -> str:
    return str(os.getenv(FALLBACK_REASON_ENV) or "").strip()


def _fallback_conflicts(agent: str, claims: Sequence[claims_gate.Claim], scopes: Sequence[str]) -> list[str]:
    normalized_agent = _norm(agent)
    conflicts = sorted(
        {
            str(claim.agent).strip()
            for claim in claims
            if _norm(claim.agent) != normalized_agent
            and any(
                _scope_matches_path(scope, fallback_scope) or _scope_matches_path(fallback_scope, scope)
                for scope in claim.scopes
                for fallback_scope in scopes
            )
        },
        key=str.lower,
    )
    return conflicts


def run(argv: Sequence[str] | None = None) -> int:
    # Honour the runtime protection toggle (requires Windows auth to disable).
    if _runtime_protection_disabled():
        print("Workboard agent claim gate: PASS (runtime protection disabled by human)")
        return 0

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
        help=("Require all staged files to be covered by the current agent's active claim scope."),
    )
    parser.add_argument(
        "--staged-scope-ignore",
        action="append",
        default=[],
        help=("Ignore staged-scope path pattern(s) while enforcing staged scope (repeatable or comma-separated)."),
    )
    parser.add_argument(
        "--enforce-clean-claimed-scope",
        action="store_true",
        help=("Require claimed scope files to be clean in the working tree (no unstaged edits in claimed paths)."),
    )
    parser.add_argument(
        "--enforce-untracked-claimed-scope",
        action="store_true",
        help=("With --enforce-clean-claimed-scope, also fail on untracked files inside claimed scope."),
    )
    parser.add_argument(
        "--claimed-scope-ignore",
        action="append",
        default=[],
        help=("Ignore claimed-scope cleanliness path patterns (repeatable or comma-separated)."),
    )
    parser.add_argument(
        "--enforce-parent-throughput",
        action="store_true",
        help=(
            "For parent-role agents, require worker fan-out when there are "
            "non-overlapping Up For Grabs tasks available."
        ),
    )
    parser.add_argument(
        "--parent-target-workers",
        type=int,
        default=2,
        help=(
            "Target minimum active workers for parent-role claims when throughput "
            "enforcement is active (default: 2)."
        ),
    )
    parser.add_argument(
        "--parent-min-ready-suggestions",
        type=int,
        default=2,
        help=(
            "Only enforce parent throughput when at least this many delegation "
            "suggestions are currently ready (default: 2)."
        ),
    )
    parser.add_argument(
        "--parent-max-suggestions",
        type=int,
        default=5,
        help=("Maximum delegation suggestions to inspect when evaluating parent throughput (default: 5)."),
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
    unresolved_owned = [
        issue for issue in issues if _norm(issue.owner) == normalized and _norm(issue.state) != "resolved"
    ]
    if unresolved_owned:
        issue_ids = [str(issue.issue_id).strip() for issue in unresolved_owned if str(issue.issue_id).strip()]
        issue_ids = sorted(set(issue_ids))
        message = (
            f"agent '{agent}' owns unresolved workboard issue(s): {', '.join(issue_ids) if issue_ids else 'unknown issue ids'}. "
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

    scope_source = SCOPE_SOURCE_CLAIM
    fallback_reason = ""
    if mine:
        scopes = sorted({scope for claim in mine for scope in claim.scopes})
    else:
        fallback_scopes = list(_fallback_scopes_from_env())
        fallback_reason = _fallback_reason_from_env()
        if not fallback_scopes:
            message = (
                f"no active workboard claim found for '{agent}'. "
                "Run scripts/crew/workboard/claim.py --claim before committing."
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
                    "scope_source": SCOPE_SOURCE_CLAIM,
                }
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard agent claim gate: FAIL")
                print(f"- {message}")
            return 1
        if not fallback_reason:
            message = (
                f"{FALLBACK_SCOPE_ENV} requires {FALLBACK_REASON_ENV} " "so fallback scope use is explicitly audited"
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
                    "scope_source": SCOPE_SOURCE_FALLBACK,
                    "fallback_reason": fallback_reason,
                    "scopes": fallback_scopes,
                }
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard agent claim gate: FAIL")
                print(f"- {message}")
            return 1

        conflicts = _fallback_conflicts(agent, claims, fallback_scopes)
        if conflicts:
            message = "explicit fallback scope overlaps active claim(s) owned by: " + ", ".join(conflicts)
            if args.json:
                payload = {
                    "gate": "workboard_agent_claim",
                    "ok": False,
                    "agent": agent,
                    "active_claim_count": len(claims),
                    "matching_claim_count": 0,
                    "unresolved_issue_count": 0,
                    "unresolved_issue_ids": [],
                    "scopes": fallback_scopes,
                    "workboard": str(workboard_path),
                    "error": message,
                    "scope_source": SCOPE_SOURCE_FALLBACK,
                    "fallback_reason": fallback_reason,
                    "conflicting_agents": conflicts,
                }
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard agent claim gate: FAIL")
                print(f"- {message}")
            return 1

        scopes = sorted(set(fallback_scopes), key=str.lower)
        scope_source = SCOPE_SOURCE_FALLBACK

    parent_throughput: dict[str, object] = {
        "checked": bool(args.enforce_parent_throughput),
        "applied": False,
        "ready_suggestion_count": 0,
        "active_worker_count": 0,
        "required_worker_count": 0,
        "target_worker_count": max(1, int(args.parent_target_workers or 1)),
        "min_ready_suggestions": max(1, int(args.parent_min_ready_suggestions or 1)),
        "generated_claim_commands": [],
    }
    if args.enforce_parent_throughput and mine:
        mine_parent_claims = [claim for claim in mine if _claim_role(claim) == "parent"]
        if mine_parent_claims:
            parent_throughput["applied"] = True
            max_suggestions = max(
                max(1, int(args.parent_target_workers or 1)),
                max(1, int(args.parent_min_ready_suggestions or 1)),
                max(1, int(args.parent_max_suggestions or 1)),
            )
            ok_suggest, suggest_result = workboard_claim_tool.suggest_delegation(
                workboard_path,
                parent_agent=mine_parent_claims[0].agent,
                max_suggestions=max_suggestions,
            )
            if not ok_suggest:
                message = f"parent throughput check failed: {suggest_result}"
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
                        "parent_throughput": parent_throughput,
                        "scope_source": scope_source,
                        "fallback_reason": fallback_reason,
                    }
                    print(json.dumps(payload, sort_keys=True))
                else:
                    print("Workboard agent claim gate: FAIL")
                    print(f"- {message}")
                return 1

            suggest_payload = dict(suggest_result) if isinstance(suggest_result, dict) else {}
            ready_suggestions = list(suggest_payload.get("ready_suggestions") or [])
            commands = list(suggest_payload.get("generated_claim_commands") or [])
            active_worker_count = int(suggest_payload.get("active_worker_count") or 0)
            ready_count = len(ready_suggestions)
            min_ready = max(1, int(args.parent_min_ready_suggestions or 1))
            target_workers = max(1, int(args.parent_target_workers or 1))
            required_workers = 0
            if ready_count >= min_ready:
                required_workers = min(target_workers, ready_count)

            parent_throughput.update(
                {
                    "ready_suggestion_count": int(ready_count),
                    "active_worker_count": int(active_worker_count),
                    "required_worker_count": int(required_workers),
                    "generated_claim_commands": commands,
                }
            )

            if required_workers > active_worker_count:
                message = (
                    f"parent agent '{agent}' has {active_worker_count} active worker claim(s), "
                    f"but {ready_count} delegation candidate(s) are ready. "
                    f"Expected at least {required_workers} active worker claim(s). "
                    "Delegate or claim additional tasks before committing."
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
                        "parent_throughput": parent_throughput,
                        "scope_source": scope_source,
                        "fallback_reason": fallback_reason,
                    }
                    print(json.dumps(payload, sort_keys=True))
                else:
                    print("Workboard agent claim gate: FAIL")
                    print(f"- {message}")
                    if commands:
                        print("- suggested worker claim command(s):")
                        for cmd in commands[: max(1, required_workers - active_worker_count)]:
                            print(f"  - {cmd}")
                return 1

    staged_scope_ignore = list(DEFAULT_STAGED_SCOPE_IGNORE)
    staged_scope_ignore.extend(_split_patterns(args.staged_scope_ignore))
    staged_files: list[str] = []
    unclaimed_staged_files: list[str] = []
    if args.enforce_staged_scope:
        staged_files = _staged_files()
        for rel_path in staged_files:
            if _is_ignored_path(rel_path, staged_scope_ignore):
                continue
            if not any(_scope_matches_path(scope, rel_path) for scope in scopes):
                unclaimed_staged_files.append(rel_path)
    if unclaimed_staged_files:
        message = (
            f"agent '{agent}' has staged files outside claimed scope. "
            "Update the WORKBOARD claim scope before committing."
        )
        if scope_source == SCOPE_SOURCE_FALLBACK:
            message = (
                f"agent '{agent}' has staged files outside the explicit fallback scope. "
                "Narrow the staged files or update the fallback scope before committing."
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
                "scope_source": scope_source,
                "fallback_reason": fallback_reason,
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

    claimed_scope_ignore = _split_patterns(args.claimed_scope_ignore)
    claimed_scope_dirty = {"unstaged": [], "untracked": []}
    if args.enforce_clean_claimed_scope:
        claimed_scope_dirty = _claimed_scope_dirty_paths(
            scopes,
            enforce_untracked=bool(args.enforce_untracked_claimed_scope),
            ignore_patterns=claimed_scope_ignore,
        )
    dirty_unstaged = list(claimed_scope_dirty.get("unstaged") or [])
    dirty_untracked = list(claimed_scope_dirty.get("untracked") or [])
    if dirty_unstaged or dirty_untracked:
        message = (
            f"agent '{agent}' has dirty files in claimed scope. Stage/commit or stash these files before committing."
        )
        if scope_source == SCOPE_SOURCE_FALLBACK:
            message = (
                f"agent '{agent}' has dirty files inside the explicit fallback scope. "
                "Stage/commit or stash these files before committing."
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
                "enforce_staged_scope": bool(args.enforce_staged_scope),
                "staged_file_count": len(staged_files),
                "staged_files_outside_scope_count": 0,
                "staged_files_outside_scope": [],
                "enforce_clean_claimed_scope": True,
                "enforce_untracked_claimed_scope": bool(args.enforce_untracked_claimed_scope),
                "claimed_scope_ignored_patterns": claimed_scope_ignore,
                "claimed_scope_unstaged_count": len(dirty_unstaged),
                "claimed_scope_unstaged_files": dirty_unstaged,
                "claimed_scope_untracked_count": len(dirty_untracked),
                "claimed_scope_untracked_files": dirty_untracked,
                "scope_source": scope_source,
                "fallback_reason": fallback_reason,
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard agent claim gate: FAIL")
            print(f"- {message}")
            if claimed_scope_ignore:
                print("- claimed-scope ignore patterns:")
                for pattern in claimed_scope_ignore:
                    print(f"  - {pattern}")
            if dirty_unstaged:
                print("- claimed-scope unstaged files:")
                for path in dirty_unstaged:
                    print(f"  - {path}")
            if dirty_untracked:
                print("- claimed-scope untracked files:")
                for path in dirty_untracked:
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
            "enforce_clean_claimed_scope": bool(args.enforce_clean_claimed_scope),
            "enforce_untracked_claimed_scope": bool(args.enforce_untracked_claimed_scope),
            "claimed_scope_ignored_patterns": claimed_scope_ignore,
            "claimed_scope_unstaged_count": 0,
            "claimed_scope_unstaged_files": [],
            "claimed_scope_untracked_count": 0,
            "claimed_scope_untracked_files": [],
            "parent_throughput": parent_throughput,
            "workboard": str(workboard_path),
            "scope_source": scope_source,
            "fallback_reason": fallback_reason,
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Workboard agent claim gate: PASS")
        print(f"- agent: {agent}")
        print(f"- matching claims: {len(mine)}")
        print(f"- scope source: {scope_source}")
        if fallback_reason:
            print(f"- fallback reason: {fallback_reason}")
        if bool(parent_throughput.get("applied")):
            print(
                "- parent throughput: "
                f"{int(parent_throughput.get('active_worker_count', 0))}/"
                f"{int(parent_throughput.get('required_worker_count', 0))} workers "
                f"(ready suggestions: {int(parent_throughput.get('ready_suggestion_count', 0))})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
