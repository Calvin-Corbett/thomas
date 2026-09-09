#!/usr/bin/env python3
"""Session-start signal collectors used by startup_router.py.

WHY THIS EXISTS (phase 1.5 Task 3 move-only split, worker.py precedent --
``scripts/crew/workboard/worker.py`` ->
``worker_pipeline.py``/``worker_dispatch.py``, commit 7f1006d7):
``startup_router.py`` was 1142 lines, over ``monolith_guard``'s unbaselined
800-line soft limit (``agent_safety.toml`` has no baseline entry for it, and
neither file is a protected file). Adding Task 3's incident-surfacing line
to that file as-is would trip the guard on an edit to an already-oversized
file. This program pays that debt with a move-only split instead of waiving
it: the functions below -- unread-inbox / current-thread / message-audit
checks, orphaned-dirty-state detection, worktree/branch inventory summaries,
and the related-branch/commit scan (keyword extraction + git search) -- are
the "gather one signal for the session-start payload" family. They share
nothing with lane classification (``classify_task`` and its helpers, which
stay in ``startup_router.py``) except the generic ``_relpath``/``_unique``
helpers, which moved here too because every extracted function that touches
paths or dedupes a list needs them.

Move-only, no logic edits. Zero dependency back on ``startup_router.py`` --
``startup_router.py`` imports every name below and re-exports it under its
original spot, so no external caller or test needs to change (see
``startup_router.py``'s import block and
``tests/test_agent_startup_router.py``, which loads ``startup_router.py``
directly by file path and never imports this module -- its calls to
``mod.classify_task``/``mod.build_startup_payload``/``mod._text_output``
still resolve every moved name through that re-export).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]

try:
    from scripts.crew.workboard import message as workboard_message
except (ImportError, ModuleNotFoundError):  # pragma: no cover
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

# Trunk-sync visibility (branch-equilibrium plan, phase 2 Task 1): unpushed
# work and a silently-failing push-gate battery were both invisible at
# session start -- this is what surfaced 746 unpushed commits only when
# someone went looking. Imported defensively, same as every collector above:
# a failure here must never break the startup router.
try:
    from scripts.crew.brief import trunk_health
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    try:
        from crew.brief import trunk_health  # type: ignore
    except (ImportError, ModuleNotFoundError):
        trunk_health = None  # type: ignore

DATE_RE = re.compile(r"Last updated:\s*(?P<value>\d{4}-\d{2}-\d{2})")


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

        # An active consolidation hold outranks everything else: it means new
        # branches are refused, so the agent must know before it tries.
        held = None
        try:
            from thomas.forge.consolidation_hold import active_hold

            held = active_hold(repo_root)
        except (ImportError, ModuleNotFoundError, OSError, ValueError):  # pragma: no cover
            held = None
        if held is not None:
            return {
                "ok": True,
                "total": report.total,
                "ceiling": report.ceiling,
                "over_ceiling": report.over_ceiling,
                "reclaimable": len(report.reclaimable),
                "needs_decision": len(report.needs_decision),
                "on_hold": True,
                "summary": report.summary(),
                "warning": held.message(),
            }

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
            "on_hold": False,
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


def _startup_trunk_health(repo_root: Path) -> dict[str, Any]:
    """Session-start trunk-sync summary (branch-equilibrium plan, phase 2
    Task 1): ``trunk_health.summarize`` already never raises, but this
    wrapper is a second, defensive backstop -- same shape as
    ``_startup_incident_surfacing`` in ``startup_router.py`` -- so session
    start cannot fail on this line no matter what."""
    if trunk_health is None:  # pragma: no cover - import guard
        return {"ok": False, "error": "trunk_health unavailable"}
    try:
        return trunk_health.summarize(repo_root)
    except (OSError, ValueError, TypeError, RuntimeError, AttributeError) as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


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
