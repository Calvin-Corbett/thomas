#!/usr/bin/env python3
"""Classify an agent task into a lightweight startup lane."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts import gate_response_policy
    from scripts.crew.workboard import message as workboard_message
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    import gate_response_policy  # type: ignore
    from crew.workboard import message as workboard_message  # type: ignore

# Worktree-sprawl prevention: surfaced at session start so every agent sees the
# worktree inventory before creating a new one. Imported defensively — a failure
# here must never break the startup router.
try:
    from scripts.crew import worktree_debt, worktree_ledger
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    try:
        from crew import worktree_debt, worktree_ledger  # type: ignore
    except (ImportError, ModuleNotFoundError):
        worktree_ledger = None  # type: ignore
        worktree_debt = None  # type: ignore

# Branch-sprawl prevention. Worktrees were counted; branches were not, so a repo
# could sit under the worktree ceiling while dozens of branches accumulated
# unseen. Surfacing this at session start is what stops an agent with no context
# from building on top of a stale branch.
try:
    from thomas.forge import branch_custodian
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    branch_custodian = None  # type: ignore

DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
ROUTER_DOC = "docs/ai/AGENT_ROUTER.md"
LANE_CARD_PATHS = {
    "chat": "docs/ai/CHECKLISTS/agent-lane-chat.md",
    "benchmark": "docs/ai/CHECKLISTS/agent-lane-benchmark.md",
    "simple-edit": "docs/ai/CHECKLISTS/agent-lane-simple-edit.md",
    "risky-edit": "docs/ai/CHECKLISTS/agent-lane-risky-edit.md",
    "multi-file": "docs/ai/CHECKLISTS/agent-lane-multi-file.md",
    "multi-agent": "docs/ai/CHECKLISTS/agent-lane-multi-agent.md",
    "ui-proof": "docs/ai/CHECKLISTS/agent-lane-ui-proof.md",
}
UI_PROOF_PREFIXES = (
    "apps/site/src/app/",
    "apps/site/src/components/",
)
RISKY_PREFIXES = (
    "thomas/server/routes/",
    "thomas/server/web/",
    "scripts/workboard_",
    "plans/thomas/",
)
WORKBOARD_REQUIRED_LANES = {"risky-edit", "multi-file", "multi-agent", "ui-proof"}
DATE_RE = re.compile(r"Last updated:\s*(?P<value>\d{4}-\d{2}-\d{2})")


def _load_agent_preflight_module():
    module_path = Path(__file__).with_name("preflight.py")
    spec = importlib.util.spec_from_file_location("crew_brief_preflight", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load preflight from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_preflight = _load_agent_preflight_module()


def _relpath(path_value: str) -> str:
    raw = str(path_value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(ROOT)
            return str(candidate).replace("\\", "/")
        except (OSError, ValueError):
            return str(candidate).replace("\\", "/")
    return raw.lstrip("./")


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _load_workflow_mode() -> str:
    try:
        from thomas.preferences.store import PreferencesStore, get_db_path

        prefs = PreferencesStore(db_path=get_db_path()).get(user_id="default")
        mode = str(getattr(getattr(prefs.advanced, "interface", None), "workflow_mode", "") or "").strip().lower()
        if mode in {"guided", "expert"}:
            return mode
    except (ImportError, AttributeError, OSError, sqlite3.Error, TypeError, ValueError):
        pass
    return "guided"


def _find_guardrails(paths: list[str]) -> list[str]:
    found: list[str] = []
    for raw in paths:
        rel = _relpath(raw)
        if not rel:
            continue
        candidate = (ROOT / rel).resolve()
        cursor = candidate if candidate.is_dir() else candidate.parent
        for parent in (cursor, *cursor.parents):
            if parent == ROOT.parent:
                break
            guard = parent / "GUARDRAILS.md"
            if guard.exists():
                try:
                    rel_guard = guard.resolve().relative_to(ROOT)
                    found.append(str(rel_guard).replace("\\", "/"))
                except (OSError, ValueError):
                    found.append(str(guard).replace("\\", "/"))
            if parent == ROOT:
                break
    return _unique(found)


def _parse_workboard_claims(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "active_claims": 0,
            "matching_claims": [],
            "conflict": False,
            "stale": False,
            "updated_at": "",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    updated_at = ""
    stale = False
    for line in text.splitlines()[:20]:
        match = DATE_RE.search(line)
        if not match:
            continue
        updated_at = match.group("value")
        try:
            then = datetime.fromisoformat(updated_at).replace(tzinfo=timezone.utc)
            stale = (datetime.now(timezone.utc) - then).days >= 7
        except ValueError:
            stale = False
        break
    in_claims = False
    claims: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_claims = stripped.lower().startswith("## agent claims")
            continue
        if not in_claims or not stripped.startswith("- "):
            continue
        token = stripped[2:].strip()
        if token.lower() in {"none", "- none"}:
            continue
        fields: dict[str, str] = {}
        for part in [piece.strip() for piece in token.split(";") if piece.strip()]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            fields[key.strip().lower()] = value.strip()
        if fields:
            claims.append(fields)
    return {
        "exists": True,
        "active_claims": len(claims),
        "claims": claims,
        "stale": stale,
        "updated_at": updated_at,
    }


def _startup_inbox(workboard_path: Path, *, agent: str = "") -> dict[str, Any]:
    actor = workboard_message.resolve_current_agent(agent)
    if not actor:
        return {
            "agent": "",
            "ok": False,
            "unread_count": 0,
            "messages": [],
            "error": "agent identity unavailable; pass --agent or set AGENT_ID/THOMAS_AGENT_ID",
        }
    ok, payload = workboard_message.unread_messages(workboard_path, agent=actor)
    messages = list(payload.get("messages") or []) if ok else []
    return {
        "agent": actor,
        "ok": bool(ok),
        "unread_count": len(messages),
        "messages": messages[:8],
        "error": "" if ok else str(payload.get("error") or "inbox check failed"),
    }


def _startup_current_thread(workboard_path: Path, *, agent: str = "", peer: str = "") -> dict[str, Any]:
    actor = workboard_message.resolve_current_agent(agent)
    peer_clean = str(peer or "").strip()
    if not actor:
        return {
            "agent": "",
            "peer": peer_clean,
            "ok": False,
            "message_count": 0,
            "awaiting_me": 0,
            "awaiting_peer": 0,
            "messages": [],
            "error": "agent identity unavailable; pass --agent or set AGENT_ID/THOMAS_AGENT_ID",
        }
    ok, payload = workboard_message.current_messages(workboard_path, agent=actor, peer=peer_clean, limit=5)
    messages = list(payload.get("messages") or []) if ok else []
    awaiting_me = sum(1 for row in messages if str(row.get("awaiting") or "") == "me")
    awaiting_peer = sum(1 for row in messages if str(row.get("awaiting") or "") == "peer")
    return {
        "agent": actor,
        "peer": peer_clean,
        "ok": bool(ok),
        "message_count": int(payload.get("message_count") or len(messages)) if ok else 0,
        "awaiting_me": awaiting_me,
        "awaiting_peer": awaiting_peer,
        "messages": messages[:5],
        "error": "" if ok else str(payload.get("error") or "current-thread check failed"),
    }


def _startup_message_audit(workboard_path: Path, *, agent: str = "", peer: str = "") -> dict[str, Any]:
    actor = workboard_message.resolve_current_agent(agent)
    peer_clean = str(peer or "").strip()
    ok, payload = workboard_message.audit_messages(workboard_path, agent=actor, peer=peer_clean, limit=5)
    return {
        "agent": actor,
        "peer": peer_clean,
        "ok": bool(ok),
        "problem_count": int(payload.get("problem_count") or 0),
        "canonical_inbox_count": int(payload.get("canonical_inbox_count") or 0),
        "canonical_current_count": int(payload.get("canonical_current_count") or 0),
        "awaiting_me": int(payload.get("awaiting_me") or 0),
        "awaiting_peer": int(payload.get("awaiting_peer") or 0),
        "parse_error_count": int(payload.get("parse_error_count") or 0),
        "candidate_mention_count": int(payload.get("candidate_mention_count") or 0),
        "identity_mismatch_count": int(payload.get("identity_mismatch_count") or 0),
        "stale_identity_mismatch_count": int(payload.get("stale_identity_mismatch_count") or 0),
        "parse_errors": list(payload.get("parse_errors") or [])[:5],
        "candidate_mentions": list(payload.get("candidate_mentions") or [])[:5],
        "identity_mismatches": list(payload.get("identity_mismatches") or [])[:5],
        "stale_identity_mismatches": list(payload.get("stale_identity_mismatches") or [])[:5],
        "diagnosis": str(payload.get("diagnosis") or ""),
        "error": "" if ok else str(payload.get("error") or "message lane audit found problems"),
    }


def _brief_text(value: object, *, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _paths_overlap(path_a: str, path_b: str) -> bool:
    a = _relpath(path_a)
    b = _relpath(path_b)
    if not a or not b:
        return False
    return a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")


def _matching_claims(paths: list[str], workboard: dict[str, Any]) -> list[dict[str, str]]:
    rows = list(workboard.get("claims") or [])
    if not paths:
        return []
    matches: list[dict[str, str]] = []
    for claim in rows:
        scope_value = str(claim.get("scope") or "")
        scopes = [item.strip() for item in scope_value.split(",") if item.strip()]
        if any(_paths_overlap(task_path, scope_path) for task_path in paths for scope_path in scopes):
            matches.append(claim)
    return matches


def _requires_ui_proof(paths: list[str]) -> bool:
    return any(_relpath(path).startswith(prefix) for path in paths for prefix in UI_PROOF_PREFIXES)


def _is_risky_path(path: str) -> bool:
    rel = _relpath(path)
    if not rel:
        return False
    if rel in {
        "AGENTS.md",
        "README.md",
        "PROJECT_INDEX.md",
        "KNOWN_ISSUES.md",
        "docs/REPO_STRUCTURE_PROTOCOL.md",
        "docs/AGENT_FILE_EDITING_RULES.md",
        "GUARDRAILS.md",
    }:
        return True
    return any(rel.startswith(prefix) for prefix in RISKY_PREFIXES)


def _subsystems(paths: list[str]) -> set[str]:
    out: set[str] = set()
    for rel in [_relpath(path) for path in paths]:
        if not rel:
            continue
        parts = [part for part in rel.split("/") if part]
        if len(parts) >= 2:
            out.add("/".join(parts[:2]))
        elif parts:
            out.add(parts[0])
    return out


def _bootstrap_command(summary: str, paths: list[str]) -> str:
    scope = ",".join(_unique([_relpath(path) for path in paths if _relpath(path)])) or "<scope>"
    task = re.sub(r"[\r\n;]+", " ", str(summary or "").strip()) or "describe the task"
    return (
        'python scripts/crew/brief/bootstrap_claim.py --agent "<agent-id>" '
        f'--scope "{scope}" --task "{task}" --no-auto-dispatch'
    )


_BRANCH_SCAN_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "can",
        "could",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "up",
        "down",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "my",
        "our",
        "add",
        "fix",
        "update",
        "create",
        "make",
        "build",
        "implement",
        "change",
        "modify",
        "edit",
        "remove",
        "delete",
        "refactor",
        "work",
        "get",
        "set",
        "new",
        "use",
        "run",
        "test",
        "check",
        "file",
        "files",
        "code",
        "module",
        "function",
        "class",
        "method",
        "thomas",
        "agent",
        "feature",
        "bug",
        "issue",
        "task",
        "page",
    }
)


def _extract_keywords(summary: str, paths: list[str]) -> list[str]:
    """Extract meaningful keywords from a task summary and file paths."""
    words: list[str] = []
    # From summary: split on non-alphanumeric, keep words >= 3 chars
    for token in re.split(r"[^a-zA-Z0-9_-]+", summary.lower()):
        token = token.strip("-_")
        if len(token) >= 3 and token not in _BRANCH_SCAN_STOP_WORDS:
            words.append(token)
    # From paths: extract meaningful directory/file name components
    for raw in paths:
        rel = _relpath(raw)
        for part in rel.replace("\\", "/").split("/"):
            name = part.split(".")[0].strip("-_").lower()
            if len(name) >= 3 and name not in _BRANCH_SCAN_STOP_WORDS:
                words.append(name)
    return _unique(words)[:8]  # Cap at 8 keywords to keep searches fast


def _scan_related_branches(summary: str, paths: list[str]) -> dict[str, Any]:
    """Scan local and remote branches/commits for existing work related to the task.

    Returns a dict with:
      - keywords: list of keywords searched
      - branches: list of matching branch names
      - commits: list of matching commit one-liners (capped at 15)
      - warning: human-readable warning string (empty if nothing found)
    """
    keywords = _extract_keywords(summary, paths)
    if not keywords:
        return {"keywords": [], "branches": [], "commits": [], "warning": ""}

    matched_branches: list[str] = []
    matched_commits: list[str] = []

    for kw in keywords:
        # Search branch names
        try:
            result = subprocess.run(
                ["git", "branch", "-a", "--list", f"*{kw}*"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(ROOT),
            )
            for line in result.stdout.strip().splitlines():
                branch = line.strip().lstrip("* ").strip()
                if branch and branch not in matched_branches:
                    matched_branches.append(branch)
        except (subprocess.SubprocessError, OSError):
            pass

        # Search commit messages
        try:
            result = subprocess.run(
                ["git", "log", "--all", "--oneline", "--grep", kw, "-n", "10"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(ROOT),
            )
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line and line not in matched_commits:
                    matched_commits.append(line)
        except (subprocess.SubprocessError, OSError):
            pass

    # Deduplicate and cap
    matched_branches = _unique(matched_branches)[:10]
    matched_commits = _unique(matched_commits)[:15]

    warning = ""
    if matched_branches or matched_commits:
        parts = []
        if matched_branches:
            branch_list = ", ".join(matched_branches[:5])
            more = f" (+{len(matched_branches) - 5} more)" if len(matched_branches) > 5 else ""
            parts.append(f"Found {len(matched_branches)} related branch(es): {branch_list}{more}")
        if matched_commits:
            parts.append(f"Found {len(matched_commits)} related commit(s) across all branches.")
        parts.append(
            "STOP and check these before creating new files. "
            "Existing work may just need a merge. Ask the user before rebuilding."
        )
        warning = " ".join(parts)

    return {
        "keywords": keywords,
        "branches": matched_branches,
        "commits": matched_commits,
        "warning": warning,
    }


def classify_task(
    *,
    summary: str,
    paths: list[str],
    edit_intent: bool,
    benchmark_mode: bool,
    tracked_work: bool,
    multi_agent: bool,
    long_running: bool,
    workflow_mode: str,
    workboard_path: Path,
) -> dict[str, Any]:
    workboard = _parse_workboard_claims(workboard_path)
    matching_claims = _matching_claims(paths, workboard)
    conflict = bool(matching_claims)
    ui_proof = _requires_ui_proof(paths)
    risky_paths = [path for path in paths if _is_risky_path(path)]
    subsystem_count = len(_subsystems(paths))
    summary_lower = str(summary or "").lower()
    delegation_keywords = any(
        token in summary_lower for token in ("delegate", "swarm", "parallel", "multi-agent", "handoff", "workers")
    )

    if benchmark_mode:
        lane = "benchmark"
    elif not edit_intent and not paths:
        lane = "chat"
    elif ui_proof:
        lane = "ui-proof"
    elif multi_agent or delegation_keywords:
        lane = "multi-agent"
    elif long_running or len(paths) >= 4 or subsystem_count >= 3:
        lane = "multi-file"
    elif tracked_work or conflict or risky_paths:
        lane = "risky-edit"
    else:
        lane = "simple-edit"

    workboard_required = (
        bool(edit_intent) or lane in WORKBOARD_REQUIRED_LANES or tracked_work or long_running or conflict or multi_agent
    )
    reads: list[str] = [ROUTER_DOC, LANE_CARD_PATHS[lane]]
    if lane != "chat":
        reads.extend(["docs/AGENT_FILE_EDITING_RULES.md", "GUARDRAILS.md"])
        reads.extend(_find_guardrails(paths))
    if workboard_required:
        reads.append("plans/thomas/WORKBOARD.md")
    if lane in {"risky-edit", "multi-file", "multi-agent"} and workflow_mode == "guided":
        reads.append("AGENTS.md")
    if lane == "multi-file" and workflow_mode == "guided":
        reads.append("docs/REPO_STRUCTURE_PROTOCOL.md")
    if lane == "multi-agent":
        reads.extend(["plans/thomas/WORKBOARD.md", "docs/ops/TASK_ECOSYSTEM_PROTOCOL.md"])
    if lane == "ui-proof":
        reads.append("skills/ui-precision-guard/SKILL.md")

    checks = {
        "chat": [],
        "benchmark": [
            "Verify benchmark env is complete: THOMAS_BENCHMARK_MODE, RUN_ID, REASON, and ROOT.",
            "Limit writes to the benchmark root only.",
            "Capture proof artifacts and benchmark audit output before handoff.",
        ],
        "simple-edit": [
            "Bootstrap a workboard claim before implementation.",
            "Run a file-level syntax or compile check for edited code.",
            "Run focused regression tests for changed behavior.",
        ],
        "risky-edit": [
            "Bootstrap or confirm the workboard claim before implementation.",
            "Run focused regression tests for changed behavior.",
            "Run python scripts/test_stepup_protocol.py when the change needs repo-wide regression confidence.",
            "Run release hygiene checks when product behavior changes.",
            "Validate workboard claim requirements if tracked work is required.",
        ],
        "multi-file": [
            "Bootstrap or confirm the workboard claim before implementation.",
            "Run focused regression tests across changed subsystems.",
            "Run python scripts/test_stepup_protocol.py and carry it through the large shard stage before handoff.",
            "Run release hygiene checks.",
            "Update plan/workboard state when execution intent changes.",
        ],
        "multi-agent": [
            "Claim scope before implementation.",
            "Use workboard messaging for blockers and coordination.",
            "Mark READY and log ACK before bundling another agent's scope.",
        ],
        "ui-proof": [
            "Run python scripts/refresh_site_visual_proof.py",
            "Run python scripts/forge/gates/site_visual_proof.py",
        ],
    }[lane]
    escalation = {
        "chat": [
            "You start editing files.",
            "The task becomes multi-file, risky, or multi-agent.",
        ],
        "benchmark": [
            "The task needs product-code edits outside the benchmark root.",
            "UI-proof or release-critical gates become required.",
        ],
        "simple-edit": [
            "Scope expands beyond a small isolated change.",
            "A claim conflict appears.",
            "Visual proof, release hygiene, or architecture review becomes required.",
        ],
        "risky-edit": [
            "The task spans multiple subsystems.",
            "Delegation or handoff becomes necessary.",
        ],
        "multi-file": [
            "Parallel lanes or delegation are required.",
            "A UI-proof or release-critical flow is added.",
        ],
        "multi-agent": [
            "UI-proof or release-critical gates also apply.",
        ],
        "ui-proof": [
            "The task also becomes multi-agent or architecture-heavy.",
        ],
    }[lane]
    return {
        "lane": lane,
        "workflow_mode": workflow_mode,
        "edit_intent": bool(edit_intent),
        "workboard_required": bool(workboard_required),
        "gate_handling": gate_response_policy.startup_gate_guidance(),
        "workboard": {
            "path": str(workboard_path),
            "active_claims": int(workboard.get("active_claims", 0) or 0),
            "matching_claims": matching_claims,
            "claim_conflict": bool(conflict),
            "stale": bool(workboard.get("stale", False)),
            "updated_at": str(workboard.get("updated_at") or ""),
        },
        "bootstrap_command": _bootstrap_command(summary, paths) if workboard_required else "",
        "flags": {
            "ui_proof": bool(ui_proof),
            "benchmark_mode": bool(benchmark_mode),
            "tracked_work": bool(tracked_work),
            "multi_agent": bool(multi_agent),
            "long_running": bool(long_running),
            "risky_paths": _unique([_relpath(path) for path in risky_paths]),
        },
        "paths": _unique([_relpath(path) for path in paths]),
        "required_reads": _unique(reads),
        "required_checks": checks,
        "escalation_triggers": escalation,
    }


def _detect_orphaned_dirty_state(repo_root: Path, max_age_hours: float = 24.0) -> dict[str, Any]:
    """Crew.Brief Layer 2 — detect orphaned dirty state from prior sessions.

    Scans ``runtime/heartbeat_dirty/`` for recent auto-checkpoint failures (L1
    records its failures there). A non-zero count of recent records implies a
    prior session left dirty work uncommitted and is no longer running. The
    payload here is informational; the recommended remediation is to run
    ``scripts/heartbeat.py --checkpoint --force`` before starting new work.
    """
    dirty_dir = repo_root / "runtime" / "heartbeat_dirty"
    if not dirty_dir.exists():
        return {
            "records_found": 0,
            "recent_records": [],
            "orphan_detected": False,
            "recommendation": "",
        }

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=float(max_age_hours))
    except (TypeError, ValueError):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24.0)

    recent: list[dict[str, Any]] = []
    for record_path in sorted(dirty_dir.glob("*.json"), reverse=True)[:50]:
        try:
            data = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        ts_raw = str(data.get("ts") or "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts >= cutoff:
            recent.append(
                {
                    "ts": ts_raw,
                    "branch": str(data.get("branch") or ""),
                    "dirty_file_count": int(data.get("dirty_file_count") or 0),
                    "dirty_paths": list(data.get("dirty_paths") or [])[:10],
                    "reason": str(data.get("reason") or "")[:200],
                    "record": record_path.name,
                }
            )

    return {
        "records_found": len(recent),
        "recent_records": recent[:5],
        "orphan_detected": bool(recent),
        "recommendation": (
            "Prior session left dirty work uncommitted. Recommended: "
            "`python scripts/heartbeat.py --checkpoint --force` to auto-checkpoint, "
            "or `python scripts/crew/brief/commit.py --message <msg>` to resolve manually "
            "before starting new work."
            if recent
            else ""
        ),
    }


def _startup_worktree_inventory(repo_root: Path) -> dict[str, Any]:
    """Surface the worktree ledger + merge-debt alarm at session start.

    Default-safe: with only the main checkout this returns a quiet summary and no
    warning. Any failure degrades to an ``ok=False`` payload rather than raising.
    """
    if worktree_ledger is None:  # pragma: no cover - import guard
        return {"ok": False, "error": "worktree_ledger unavailable", "summary": "", "warning": ""}
    try:
        ledger = worktree_ledger.collect(repo_root)
        rows = [
            {
                "branch": row.branch or ("(main)" if row.is_main else "(detached)"),
                "purpose": row.purpose,
                "uncommitted": row.uncommitted_count,
                "days_since_last_commit": row.days_since_last_commit,
                "dirty": row.dirty,
                "stale": row.stale,
                "is_main": row.is_main,
            }
            for row in ledger.rows
        ]
        warning = ""
        if worktree_debt is not None:
            report = worktree_debt.assess_debt(repo_root)
            if report.over_ceiling:
                warning = worktree_debt.render_report(report)
        return {
            "ok": True,
            "total": ledger.total,
            "dirty": ledger.dirty_count,
            "stale": ledger.stale_count,
            "over_ceiling": ledger.over_ceiling,
            "header": worktree_ledger.header_line(ledger),
            "summary": worktree_ledger.summary_line(ledger),
            "worktrees": rows,
            "warning": warning,
        }
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc), "summary": "", "warning": ""}


def _startup_branch_inventory(repo_root: Path, *, trunk: str = "dev") -> dict[str, Any]:
    """Surface branch sprawl at session start, beside the worktree inventory.

    This is the awareness that prevents the recurring failure: an agent arriving
    with no context, seeing a tidy worktree list, and happily branching again on
    top of a pile nobody is tracking. Degrades quietly -- never raises.
    """
    if branch_custodian is None:  # pragma: no cover - import guard
        return {"ok": False, "error": "branch_custodian unavailable", "summary": "", "warning": ""}
    try:
        git = branch_custodian.subprocess_git_runner(str(repo_root))
        report = branch_custodian.survey(git, trunk=trunk)
        warning = ""
        if report.over_ceiling:
            warning = (
                f"BRANCH SPRAWL: {report.total} branches (ceiling {report.ceiling}). "
                f"{len(report.reclaimable)} can be retired automatically; "
                f"{len(report.needs_decision)} carry unique work. "
                "Run `thomas consolidate` before creating another branch."
            )
        return {
            "ok": True,
            "total": report.total,
            "ceiling": report.ceiling,
            "over_ceiling": report.over_ceiling,
            "reclaimable": len(report.reclaimable),
            "needs_decision": len(report.needs_decision),
            "summary": report.summary(),
            "warning": warning,
        }
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
        branch_custodian.BranchCustodianError,
    ) as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc), "summary": "", "warning": ""}


def build_startup_payload(
    *,
    summary: str,
    paths: list[str],
    edit_intent: bool,
    benchmark_mode: bool,
    tracked_work: bool,
    multi_agent: bool,
    long_running: bool,
    workflow_mode: str,
    workboard_path: Path,
    cwd: Path | None = None,
    agent: str = "",
    peer: str = "",
) -> dict[str, Any]:
    payload = classify_task(
        summary=summary,
        paths=paths,
        edit_intent=edit_intent,
        benchmark_mode=benchmark_mode,
        tracked_work=tracked_work,
        multi_agent=multi_agent,
        long_running=long_running,
        workflow_mode=workflow_mode,
        workboard_path=workboard_path,
    )
    payload["preflight"] = agent_preflight.evaluate_preflight(root=ROOT, cwd=cwd)
    payload["inbox"] = _startup_inbox(workboard_path, agent=agent)
    payload["current_thread"] = _startup_current_thread(workboard_path, agent=agent, peer=peer)
    payload["message_audit"] = _startup_message_audit(workboard_path, agent=agent, peer=peer)
    payload["branch_scan"] = _scan_related_branches(summary, paths)
    payload["orphaned_state"] = _detect_orphaned_dirty_state(ROOT)
    payload["worktree_inventory"] = _startup_worktree_inventory(ROOT)
    payload["branch_inventory"] = _startup_branch_inventory(ROOT)
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify a Thomas agent task into a startup lane.")
    parser.add_argument("--summary", default="", help="Short task summary.")
    parser.add_argument("--path", action="append", default=[], help="Repo-relative path the task will touch.")
    parser.add_argument("--edit-intent", action="store_true", help="Set when the task will edit files.")
    parser.add_argument("--benchmark", action="store_true", help="Set when the task is a benchmark-lane run.")
    parser.add_argument(
        "--tracked-work", action="store_true", help="Set when the task should be tracked on the workboard."
    )
    parser.add_argument(
        "--multi-agent", action="store_true", help="Set when the task needs delegation or swarm behavior."
    )
    parser.add_argument(
        "--long-running", action="store_true", help="Set when the task is expected to stay active across handoffs."
    )
    parser.add_argument(
        "--workflow-mode",
        choices=("guided", "expert"),
        default="",
        help="Override the saved workflow mode preference.",
    )
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD), help="Path to WORKBOARD.md.")
    parser.add_argument("--agent", default="", help="Agent identity for startup inbox surfacing.")
    parser.add_argument("--peer", default="", help="Optional peer identity for startup current-thread surfacing.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser


def _text_output(payload: dict[str, Any]) -> str:
    preflight = dict(payload.get("preflight") or {})
    policy = dict(preflight.get("policy") or {})
    lines = ["Thomas agent startup router"]
    worktree_inventory = dict(payload.get("worktree_inventory") or {})
    if worktree_inventory.get("ok"):
        lines.append(str(worktree_inventory.get("header") or worktree_inventory.get("summary") or ""))
        if int(worktree_inventory.get("total") or 0) > 1:
            for row in list(worktree_inventory.get("worktrees") or []):
                if row.get("is_main"):
                    continue
                marks = []
                if row.get("dirty"):
                    marks.append("DIRTY")
                if row.get("stale"):
                    marks.append("STALE")
                flag = f" [{','.join(marks)}]" if marks else ""
                age = row.get("days_since_last_commit")
                age_text = "?" if age is None else f"{age}d"
                lines.append(
                    f"  - {row.get('branch')}{flag}: {row.get('uncommitted')} uncommitted, {age_text} "
                    f"({row.get('purpose')})"
                )
        warning = str(worktree_inventory.get("warning") or "").strip()
        if warning:
            lines.append("*** WORKTREE MERGE-DEBT WARNING ***")
            lines.extend(warning.splitlines())
    inbox = dict(payload.get("inbox") or {})
    inbox_agent = str(inbox.get("agent") or "")
    inbox_count = int(inbox.get("unread_count") or 0)
    if inbox.get("ok"):
        lines.append(f"inbox: agent={inbox_agent}; unread={inbox_count}")
        for row in list(inbox.get("messages") or []):
            escalation = " ESCALATED" if str(row.get("escalation") or "").strip() else ""
            lines.append(
                "  - "
                f"{row.get('msg_id')}: from={row.get('from')} priority={row.get('priority')}{escalation}; "
                f"{_brief_text(row.get('summary'))}"
            )
        if inbox_count:
            lines.append(f"inbox_action: python scripts/crew/workboard/message.py --inbox --agent {inbox_agent}")
    else:
        lines.append(f"inbox: unavailable; {inbox.get('error', 'unknown inbox error')}")
    current_thread = dict(payload.get("current_thread") or {})
    if current_thread.get("ok"):
        thread_agent = str(current_thread.get("agent") or inbox_agent)
        thread_peer = str(current_thread.get("peer") or "").strip()
        thread_count = int(current_thread.get("message_count") or 0)
        awaiting_me = int(current_thread.get("awaiting_me") or 0)
        awaiting_peer = int(current_thread.get("awaiting_peer") or 0)
        peer_suffix = f"; peer={thread_peer}" if thread_peer else ""
        lines.append(
            f"current_thread: agent={thread_agent}{peer_suffix}; active={thread_count}; "
            f"awaiting_me={awaiting_me}; awaiting_peer={awaiting_peer}"
        )
        for row in list(current_thread.get("messages") or []):
            lines.append(
                "  - "
                f"{row.get('msg_id')}: {row.get('direction')} awaiting={row.get('awaiting')} "
                f"state={row.get('state')}; {_brief_text(row.get('summary'))}"
            )
        if thread_count:
            peer_arg = f" --peer {thread_peer}" if thread_peer else ""
            lines.append(
                f"current_thread_action: python scripts/crew/workboard/message.py --current --agent {thread_agent}{peer_arg}"
            )
    elif current_thread:
        lines.append(f"current_thread: unavailable; {current_thread.get('error', 'unknown current-thread error')}")
    message_audit = dict(payload.get("message_audit") or {})
    if message_audit:
        audit_state = "ok" if message_audit.get("ok") else "warning"
        lines.append(
            f"message_audit: {audit_state}; problems={int(message_audit.get('problem_count') or 0)}; "
            f"inbox={int(message_audit.get('canonical_inbox_count') or 0)}; "
            f"current={int(message_audit.get('canonical_current_count') or 0)}; "
            f"awaiting_me={int(message_audit.get('awaiting_me') or 0)}; "
            f"awaiting_peer={int(message_audit.get('awaiting_peer') or 0)}; "
            f"{message_audit.get('diagnosis', '')}"
        )
        for item in list(message_audit.get("parse_errors") or []):
            lines.append(f"  - parse_error line {item.get('line')}: {_brief_text(item.get('error'), limit=120)}")
        for item in list(message_audit.get("candidate_mentions") or []):
            lines.append(f"  - candidate_mention line {item.get('line')}: {_brief_text(item.get('text'), limit=160)}")
    if preflight:
        lines.extend(
            [
                f"preflight_status: {preflight['status']}",
                f"preflight_summary: {preflight['summary']}",
                f"preflight_policy: {policy.get('summary', '')}",
            ]
        )
        checks = list(preflight.get("checks") or [])
        if checks:
            lines.append("preflight_checks:")
            for check in checks:
                action = str(check.get("user_action") or "").strip()
                suffix = f" | action: {action}" if action and check.get("status") != "ok" else ""
                lines.append(
                    f"  - {check.get('status', 'unknown')} {check.get('id', 'check')}: {check.get('message', '')}{suffix}"
                )
    lines.extend(
        [
            f"lane: {payload['lane']}",
            f"workflow_mode: {payload['workflow_mode']}",
            f"workboard_required: {payload['workboard_required']}",
            (
                "workboard: "
                f"{payload['workboard']['active_claims']} active claims"
                + ("; conflict detected" if payload["workboard"]["claim_conflict"] else "")
                + ("; metadata stale" if payload["workboard"]["stale"] else "")
            ),
        ]
    )
    if payload.get("bootstrap_command"):
        lines.append(f"bootstrap_command: {payload['bootstrap_command']}")
    gate_handling = dict(payload.get("gate_handling") or {})
    if gate_handling:
        lines.append(f"gate_handling: {gate_handling.get('summary', '')}")
        auto_remediate = list(gate_handling.get("auto_remediate") or [])
        hard_stop = list(gate_handling.get("hard_stop") or [])
        if auto_remediate:
            lines.append("auto_remediate_gates:")
            lines.extend([f"  - {item}" for item in auto_remediate])
        if hard_stop:
            lines.append("hard_stop_gates:")
            lines.extend([f"  - {item}" for item in hard_stop])
    if payload["paths"]:
        lines.append("paths:")
        lines.extend([f"  - {path}" for path in payload["paths"]])
    lines.append("required_reads:")
    lines.extend([f"  - {item}" for item in payload["required_reads"]])
    lines.append("required_checks:")
    if payload["required_checks"]:
        lines.extend([f"  - {item}" for item in payload["required_checks"]])
    else:
        lines.append("  - none")
    lines.append("escalate_when:")
    lines.extend([f"  - {item}" for item in payload["escalation_triggers"]])
    orphaned_state = dict(payload.get("orphaned_state") or {})
    if orphaned_state.get("orphan_detected"):
        lines.append("")
        lines.append("*** ORPHANED DIRTY STATE WARNING (Crew.Brief L2) ***")
        lines.append(
            f"Found {orphaned_state.get('records_found', 0)} recent heartbeat-checkpoint failure "
            f"record(s) in runtime/heartbeat_dirty/. A prior session left work uncommitted."
        )
        for record in list(orphaned_state.get("recent_records") or [])[:3]:
            ts = str(record.get("ts") or "")
            branch = str(record.get("branch") or "")
            count = record.get("dirty_file_count") or 0
            lines.append(f"  - {ts} on {branch}: {count} dirty file(s)")
        recommendation = str(orphaned_state.get("recommendation") or "").strip()
        if recommendation:
            lines.append(f"RECOMMENDATION: {recommendation}")

    branch_scan = dict(payload.get("branch_scan") or {})
    warning = str(branch_scan.get("warning") or "").strip()
    if warning:
        lines.append("")
        lines.append("*** BRANCH SCAN WARNING ***")
        lines.append(warning)
        branches = list(branch_scan.get("branches") or [])
        if branches:
            lines.append("matching_branches:")
            lines.extend([f"  - {b}" for b in branches])
        commits = list(branch_scan.get("commits") or [])
        if commits:
            lines.append("matching_commits:")
            lines.extend([f"  - {c}" for c in commits[:10]])
        lines.append(
            "ACTION REQUIRED: Review these branches/commits before creating new files. "
            "Run 'git log --oneline master..<branch>' to inspect. Ask the user before rebuilding."
        )
    return "\n".join(lines)


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    workflow_mode = str(args.workflow_mode or "").strip().lower() or _load_workflow_mode()
    payload = build_startup_payload(
        summary=str(args.summary or ""),
        paths=list(args.path or []),
        edit_intent=bool(args.edit_intent),
        benchmark_mode=bool(args.benchmark),
        tracked_work=bool(args.tracked_work),
        multi_agent=bool(args.multi_agent),
        long_running=bool(args.long_running),
        workflow_mode=workflow_mode,
        workboard_path=Path(str(args.workboard)).expanduser(),
        agent=str(args.agent or ""),
        peer=str(args.peer or ""),
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_text_output(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
