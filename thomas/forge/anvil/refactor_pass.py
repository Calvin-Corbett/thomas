"""Refactor pass -- mandatory first phase of every evolution session.

This module runs before creative/feature evolve passes.  It:
1. Runs the sweep scanner to detect oversized files and violations.
2. Consults the health ledger for staleness and priority.
3. Generates targeted refactor prompts for the agent.
4. Executes refactor agent passes in the green mirror.
5. Updates the health ledger with results.

The refactor pass is NOT optional -- if violations exist, it runs first.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import tomllib

from .doppelganger import SUPERVISOR_OWNED_PATHS
from .health_ledger import (
    build_review_queue,
    load_health_ledger,
    save_health_ledger,
    scan_python_files,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HARD_LIMIT = 1500  # New hard limit -- files above this MUST be refactored
SOFT_LIMIT = 800  # Soft limit -- files above this get flagged for review
MAX_REFACTOR_TARGETS = 5  # Don't try to refactor more than 5 files per session
REVIEW_MAX_AGE_HOURS = 168.0  # 1 week -- files reviewed within this are skipped
REFACTOR_BLOCKED_PREFIXES = ("tests/", "scripts/", "thomas/forge/anvil/")
PROTECTED_CONFIG_KEYS = ("policy_files", "guardrails_files", "enforcement_files", "enforcement_scripts")


@dataclass
class RefactorTarget:
    """A file identified for refactoring."""

    path: str
    line_count: int
    reason: str  # "oversized" | "stale" | "needs_work"
    priority: int = 0  # lower = higher priority


@dataclass
class RefactorPlan:
    """Plan for the refactor pass."""

    targets: list[RefactorTarget] = field(default_factory=list)
    skipped_recently_reviewed: int = 0
    skipped_ineligible: int = 0
    total_violations: int = 0

    @property
    def has_work(self) -> bool:
        return len(self.targets) > 0


# ---------------------------------------------------------------------------
# Detection -- find what needs refactoring
# ---------------------------------------------------------------------------


def detect_oversized_files(project_root: Path) -> list[dict[str, Any]]:
    """Find all Python files exceeding the hard limit."""
    all_files = scan_python_files(project_root)
    return [f for f in all_files if f["line_count"] > HARD_LIMIT]


def detect_soft_violations(project_root: Path) -> list[dict[str, Any]]:
    """Find files between soft and hard limit (review candidates)."""
    all_files = scan_python_files(project_root)
    return [f for f in all_files if SOFT_LIMIT < f["line_count"] <= HARD_LIMIT]


def _normalize_refactor_path(path: Any) -> str:
    return str(path or "").replace("\\", "/").lstrip("./")


def _load_refactor_protected_paths(project_root: Path) -> set[str]:
    protected = {_normalize_refactor_path(path) for path in SUPERVISOR_OWNED_PATHS}
    config_path = project_root / "agent_safety.toml"
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return protected

    protected_config = payload.get("protected")
    if not isinstance(protected_config, dict):
        return protected
    for key in PROTECTED_CONFIG_KEYS:
        rows = protected_config.get(key) or []
        if isinstance(rows, list):
            protected.update(_normalize_refactor_path(item) for item in rows if str(item).strip())
    return protected


def _is_refactor_eligible(path: Any, protected_paths: set[str]) -> bool:
    rel = _normalize_refactor_path(path)
    if not rel or rel in protected_paths:
        return False
    if any(item.endswith("/") and rel.startswith(item.rstrip("/") + "/") for item in protected_paths):
        return False
    return not any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in REFACTOR_BLOCKED_PREFIXES)


def _append_refactor_target(
    plan: RefactorPlan,
    *,
    path: Any,
    line_count: int,
    reason: str,
    priority: int,
    protected_paths: set[str],
) -> None:
    rel = _normalize_refactor_path(path)
    if not _is_refactor_eligible(rel, protected_paths):
        plan.skipped_ineligible += 1
        return
    if any(t.path == rel for t in plan.targets):
        return
    plan.targets.append(
        RefactorTarget(
            path=rel,
            line_count=int(line_count),
            reason=reason,
            priority=priority,
        )
    )


def build_refactor_plan(project_root: Path) -> RefactorPlan:
    """Build the prioritised refactor plan.

    Priority order:
    1. Files exceeding hard limit (MUST fix)
    2. Files with "needs_work" status in the health ledger
    3. Stale files exceeding soft limit (oldest first)
    """
    ledger = load_health_ledger(project_root)
    plan = RefactorPlan()
    protected_paths = _load_refactor_protected_paths(project_root)

    # Priority 1: Hard limit violations
    oversized = detect_oversized_files(project_root)
    plan.total_violations = len(oversized)
    for f in oversized:
        _append_refactor_target(
            plan,
            path=f["path"],
            line_count=int(f["line_count"]),
            reason="oversized",
            priority=0,
            protected_paths=protected_paths,
        )

    # Priority 2: Files marked "needs_work" in the ledger
    for path, rec in ledger.records.items():
        if rec.status == "needs_work":
            _append_refactor_target(
                plan,
                path=path,
                line_count=rec.line_count,
                reason="needs_work",
                priority=1,
                protected_paths=protected_paths,
            )

    # Priority 3: Stale soft-limit violations (oldest reviewed first)
    review_queue = build_review_queue(
        project_root,
        ledger,
        max_age_hours=REVIEW_MAX_AGE_HOURS,
        min_lines=SOFT_LIMIT,
    )
    for item in review_queue:
        _append_refactor_target(
            plan,
            path=item["path"],
            line_count=int(item["line_count"]),
            reason="stale",
            priority=2,
            protected_paths=protected_paths,
        )

    # Sort by priority, then by line count descending (biggest first within tier)
    plan.targets.sort(key=lambda t: (t.priority, -t.line_count))

    # Cap the number of targets per session
    if len(plan.targets) > MAX_REFACTOR_TARGETS:
        plan.skipped_recently_reviewed = len(plan.targets) - MAX_REFACTOR_TARGETS
        plan.targets = plan.targets[:MAX_REFACTOR_TARGETS]

    return plan


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------


def build_refactor_prompt(target: RefactorTarget) -> str:
    """Build a targeted refactor prompt for a single file."""
    lines = [
        "You are Thomas running a MANDATORY refactor pass in the green doppelganger mirror.",
        "",
        f"TARGET FILE: {target.path} ({target.line_count} lines)",
        f"HARD LIMIT: {HARD_LIMIT} lines",
        f"SOFT LIMIT: {SOFT_LIMIT} lines",
        "",
        "YOUR TASK:",
    ]

    if target.reason == "oversized":
        lines.extend(
            [
                f"This file EXCEEDS the hard limit of {HARD_LIMIT} lines and MUST be split.",
                "Refactor it into smaller, cohesive modules with descriptive names.",
                "Do NOT create *_part*.py or *.part*.py files -- those are banned.",
                "Split by responsibility: group related functions/classes into their own modules.",
                "Maintain all public API -- existing imports from other files must still work.",
            ]
        )
    elif target.reason == "needs_work":
        lines.extend(
            [
                "This file was previously flagged as needing work.",
                "Review it for: oversized functions, poor error handling, missing type hints,",
                "silent exception swallowing, and opportunities to extract helper modules.",
            ]
        )
    else:
        lines.extend(
            [
                f"This file is {target.line_count} lines (above soft limit of {SOFT_LIMIT}).",
                "Review it and improve code quality. If it can be split cleanly, do so.",
                "If the code is cohesive and splitting would hurt readability, document why",
                "and focus on other improvements: better error handling, type hints, logging.",
            ]
        )

    lines.extend(
        [
            "",
            "RULES:",
            "- Work only in the current cwd (the green mirror).",
            "- The green mirror has no .git metadata -- do not rely on git commands.",
            "- Never modify tests, policy files, guardrails, or enforcement scripts.",
            "- If a check fails because of environment limits, report it instead of editing the guard.",
            "- Do NOT create *_part*.py or *.part*.py files.",
            "- Do NOT use exec() to load code from other files -- use normal imports.",
            "- Use `diff.create` for targeted patches or `fs.write_file` for full-file rewrites.",
            "- Shell/process tools are disabled in self-development; use Thomas file and diff tools.",
            "- Every except Exception: must have logger.exception() and a comment.",
            "- Run `python -m py_compile <modified-file>` on every Python file you modify.",
            "- End with a concise summary of what you changed and why.",
        ]
    )

    return "\n".join(lines).strip()


def build_health_review_prompt(files: list[dict[str, Any]]) -> str:
    """Build a prompt for the agent to review a batch of files for health."""
    file_list = "\n".join(f"  - {f['path']} ({f['line_count']} lines)" for f in files[:10])
    return f"""You are Thomas running a CODE HEALTH REVIEW pass in the green doppelganger mirror.

Review the following files for code quality issues:
{file_list}

For each file, check:
1. Silent exception swallowing (except Exception: without logging)
2. Missing type hints on public functions
3. Functions over 50 lines that could be extracted
4. print() statements that should be logger calls
5. Hardcoded values that should be config
6. Missing docstrings on public classes/functions

For each file, output a one-line verdict:
  PASS: <filename> -- code quality acceptable
  NEEDS_WORK: <filename> -- <brief reason>

Then fix what you can in the NEEDS_WORK files. Prioritise silent exception
handlers and missing logging -- those hide production bugs.

RULES:
- Work only in the current cwd (the green mirror).
- Do not create new files unless extracting a module.
- Use `diff.create` for targeted patches or `fs.write_file` for full-file rewrites.
- Shell/process tools are disabled in self-development; use Thomas file and diff tools.
- Run py_compile on every file you modify.
- End with a summary of changes made.""".strip()


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_refactor_pass(
    project_root: Path,
    paths: Any,
    *,
    green_env: dict[str, str],
    green_python: str = "",
    timeout_seconds: int = 1800,
    profile: str = "",
    run_exec: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute the refactor pass. Returns results dict.

    This imports _run_exec from evolve to avoid duplicating subprocess logic.
    """
    from .evolve import _build_green_chat_command, _run_exec

    python_bin = green_python or sys.executable
    execute = run_exec or _run_exec
    plan = build_refactor_plan(project_root)

    results: dict[str, Any] = {
        "phase": "refactor",
        "targets_found": len(plan.targets),
        "total_violations": plan.total_violations,
        "skipped": plan.skipped_recently_reviewed,
        "skipped_ineligible": plan.skipped_ineligible,
        "pass_results": [],
        "health_reviews": [],
    }

    if not plan.has_work:
        logger.info("Refactor pass: no targets found, skipping.")
        results["skipped_reason"] = "no_violations"
        return results

    logger.info(
        "Refactor pass: %d targets (%d hard violations)",
        len(plan.targets),
        plan.total_violations,
    )

    # Phase 1: Refactor oversized files
    for target in plan.targets:
        if target.reason != "oversized":
            continue
        prompt = build_refactor_prompt(target)
        command = _build_green_chat_command(python_bin, profile, prompt)

        result = execute(
            command,
            cwd=paths.green_root,
            env=green_env,
            timeout_seconds=timeout_seconds,
        )
        result["target"] = target.path
        result["reason"] = target.reason
        results["pass_results"].append(result)

    # Phase 2: Health review for stale/needs_work files
    review_targets = [t for t in plan.targets if t.reason in ("stale", "needs_work")]
    if review_targets:
        files_info = [{"path": t.path, "line_count": t.line_count} for t in review_targets]
        prompt = build_health_review_prompt(files_info)
        command = _build_green_chat_command(python_bin, profile, prompt)

        result = execute(
            command,
            cwd=paths.green_root,
            env=green_env,
            timeout_seconds=timeout_seconds,
        )
        result["targets"] = [t.path for t in review_targets]
        results["health_reviews"].append(result)

    # Update health ledger
    ledger = load_health_ledger(project_root)
    session_id = datetime.now(timezone.utc).strftime("refactor-%Y%m%d-%H%M%S")
    for target in plan.targets:
        # Check if the file was successfully handled
        passed = all(
            int(r.get("returncode") or 0) == 0 for r in results["pass_results"] if r.get("target") == target.path
        )
        ledger.mark_reviewed(
            target.path,
            status="pass" if passed else "needs_work",
            line_count=target.line_count,
            notes=f"Refactor pass {target.reason}",
            reviewed_by=session_id,
        )
    save_health_ledger(project_root, ledger)

    return results
