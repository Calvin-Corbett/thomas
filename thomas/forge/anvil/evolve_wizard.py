"""Evolution wizard — interactive, tiered evolution session launcher.

Provides a structured way to configure and launch evolution sessions:

Tier 1: "Full Send" — automatic order of precedence:
    1. Run health audit (consult ledger, prioritise stale code)
    2. Refactor pass (fix violations, improve code quality)
    3. Senior-engineer pass (architecture, patterns, efficiency)
    4. Feature pass (if charter has a feature goal)
    5. Verification and optional promotion

Tier 2: Focused — pick your area:
    - "refactor"    — only refactoring and code health
    - "features"    — only new features / enhancements
    - "efficiency"  — performance, latency, resource usage
    - "reliability" — error handling, tests, resilience
    - "security"    — audit for vulnerabilities, hardening

Tier 3: Custom — full control over goal, passes, and promotion

All tiers end with a confirmation step and warning before execution.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .health_ledger import build_review_queue, load_health_ledger
from .refactor_pass import (
    HARD_LIMIT,
    SOFT_LIMIT,
    detect_oversized_files,
    detect_soft_violations,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and config
# ---------------------------------------------------------------------------


class EvolveTier(str, Enum):
    FULL_SEND = "full_send"
    FOCUSED = "focused"
    CUSTOM = "custom"


class EvolveFocus(str, Enum):
    REFACTOR = "refactor"
    FEATURES = "features"
    EFFICIENCY = "efficiency"
    RELIABILITY = "reliability"
    SECURITY = "security"


# Goals for each focus area
FOCUS_GOALS: dict[str, str] = {
    "refactor": (
        "Review and refactor the codebase for code quality. "
        "Fix oversized files, improve error handling, add missing type hints, "
        "replace print() with logging, and extract overly complex functions."
    ),
    "features": (
        "Implement the highest-priority pending feature or enhancement. "
        "Check the project roadmap and issue tracker for what to build next."
    ),
    "efficiency": (
        "Profile and optimise the codebase for performance. "
        "Focus on: reducing startup latency, optimising hot paths, "
        "eliminating redundant I/O, and improving memory usage."
    ),
    "reliability": (
        "Improve the reliability and resilience of the codebase. "
        "Add missing error handling, improve test coverage for critical paths, "
        "add retry logic for external calls, and fix any silent failure modes."
    ),
    "security": (
        "Audit the codebase for security vulnerabilities. "
        "Check for: SQL injection risks, hardcoded secrets, unsafe deserialization, "
        "missing input validation, and overly broad file permissions."
    ),
}

# Duration presets (in passes and timeout)
DURATION_PRESETS: dict[str, dict[str, int]] = {
    "quick": {"passes": 1, "timeout_seconds": 900},
    "standard": {"passes": 3, "timeout_seconds": 1800},
    "thorough": {"passes": 5, "timeout_seconds": 3600},
    "deep": {"passes": 8, "timeout_seconds": 7200},
}


# ---------------------------------------------------------------------------
# Wizard session — captures all choices before execution
# ---------------------------------------------------------------------------


@dataclass
class EvolveWizardSession:
    """Captures all wizard choices before launching an evolution session."""

    tier: str = EvolveTier.FULL_SEND.value
    focus: str = ""
    goal: str = ""
    duration: str = "standard"
    passes: int = 3
    timeout_seconds: int = 1800
    promote_on_pass: bool = False
    refactor_first: bool = True
    confirmed: bool = False
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvolveWizardSession:
        return cls(**{k: v for k, v in payload.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Pre-flight report — what the user sees before confirming
# ---------------------------------------------------------------------------


def build_preflight_report(project_root: Path, session: EvolveWizardSession) -> dict[str, Any]:
    """Build a summary of what the evolution session will do.

    This is shown to the user before they confirm.
    """
    # Gather current state
    oversized = detect_oversized_files(project_root)
    soft_violations = detect_soft_violations(project_root)
    ledger = load_health_ledger(project_root)
    review_queue = build_review_queue(project_root, ledger, min_lines=100)

    report: dict[str, Any] = {
        "tier": session.tier,
        "focus": session.focus or "full_send (automatic)",
        "goal": session.goal or "(automatic — follows order of precedence)",
        "duration": session.duration,
        "passes": session.passes,
        "timeout_minutes": session.timeout_seconds // 60,
        "promote_on_pass": session.promote_on_pass,
        "refactor_first": session.refactor_first,
        "codebase_health": {
            "hard_limit_violations": len(oversized),
            "soft_limit_violations": len(soft_violations),
            "files_needing_review": len(review_queue),
            "hard_limit": HARD_LIMIT,
            "soft_limit": SOFT_LIMIT,
        },
        "warnings": [],
    }

    # Build warnings
    report["warnings"].append(
        "This will run autonomous AI agents on your codebase in an isolated green mirror. "
        "Changes will NOT affect your live code until explicitly promoted."
    )
    if oversized:
        report["warnings"].append(
            f"{len(oversized)} file(s) exceed the hard limit of {HARD_LIMIT} lines and will be refactored first."
        )
    if session.promote_on_pass:
        report["warnings"].append(
            "Auto-promote is ON. If all verification passes, changes will be "
            "automatically applied to your live codebase."
        )
    if session.passes > 5:
        report["warnings"].append(
            f"Running {session.passes} passes — this may take a long time "
            f"(up to {session.timeout_seconds * session.passes // 60} minutes)."
        )

    return report


# ---------------------------------------------------------------------------
# Wizard flow — step by step
# ---------------------------------------------------------------------------


def wizard_step_tier() -> dict[str, Any]:
    """Return options for step 1: choose evolution tier."""
    return {
        "step": 1,
        "question": "How do you want to evolve?",
        "options": [
            {
                "key": "full_send",
                "label": "Full Send",
                "description": (
                    "Automatic — follows order of precedence: "
                    "health audit → refactor → senior-engineer review → features → verify. "
                    "The recommended option."
                ),
            },
            {
                "key": "focused",
                "label": "Focused",
                "description": (
                    "Pick a specific area to focus on: refactoring, features, efficiency, reliability, or security."
                ),
            },
            {
                "key": "custom",
                "label": "Custom",
                "description": "Full control — set your own goal, number of passes, and options.",
            },
        ],
    }


def wizard_step_focus() -> dict[str, Any]:
    """Return options for step 2 (focused tier): choose focus area."""
    return {
        "step": 2,
        "question": "What do you want to focus on?",
        "options": [
            {
                "key": "refactor",
                "label": "Refactor & Code Quality",
                "description": "Fix oversized files, improve error handling, clean up code.",
            },
            {
                "key": "features",
                "label": "New Features",
                "description": "Build the next high-priority feature or enhancement.",
            },
            {
                "key": "efficiency",
                "label": "Performance & Efficiency",
                "description": "Optimise hot paths, reduce latency, improve resource usage.",
            },
            {
                "key": "reliability",
                "label": "Reliability & Testing",
                "description": "Better error handling, more tests, resilience improvements.",
            },
            {
                "key": "security",
                "label": "Security Audit",
                "description": "Find and fix vulnerabilities, harden the codebase.",
            },
        ],
    }


def wizard_step_duration() -> dict[str, Any]:
    """Return options for step 3: how long to evolve."""
    return {
        "step": 3,
        "question": "How long should evolution run?",
        "options": [
            {
                "key": "quick",
                "label": "Quick (1 pass, ~15 min)",
                "description": "One focused pass. Good for small, targeted improvements.",
            },
            {
                "key": "standard",
                "label": "Standard (3 passes, ~45 min)",
                "description": "Multiple passes with iteration. The recommended option.",
            },
            {
                "key": "thorough",
                "label": "Thorough (5 passes, ~1.5 hrs)",
                "description": "Deep work with multiple improvement cycles.",
            },
            {
                "key": "deep",
                "label": "Deep (8 passes, ~3 hrs)",
                "description": "Maximum depth. Use for major refactors or overhauls.",
            },
        ],
    }


def wizard_step_confirm(
    project_root: Path,
    session: EvolveWizardSession,
) -> dict[str, Any]:
    """Return the confirmation step with preflight report and warnings."""
    report = build_preflight_report(project_root, session)
    return {
        "step": 4,
        "question": "Confirm evolution session?",
        "report": report,
        "warning": (
            "⚠ This will cause Thomas to modify its own codebase autonomously. "
            "Changes are isolated in a green mirror until promoted, but "
            "unexpected results are possible. Proceed?"
        ),
        "options": [
            {"key": "confirm", "label": "Yes, evolve"},
            {"key": "cancel", "label": "Cancel"},
        ],
    }


# ---------------------------------------------------------------------------
# Session builder — assemble wizard choices into an EvolveWizardSession
# ---------------------------------------------------------------------------


def build_wizard_session(
    tier: str,
    focus: str = "",
    duration: str = "standard",
    goal: str = "",
    promote_on_pass: bool = False,
) -> EvolveWizardSession:
    """Assemble wizard choices into a session config."""
    dur = DURATION_PRESETS.get(duration, DURATION_PRESETS["standard"])
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # Determine goal
    if tier == EvolveTier.FULL_SEND.value:
        resolved_goal = (
            "Follow this order of precedence: "
            "1) Run health audit and identify stale/problematic files. "
            "2) Refactor any files exceeding size limits or with known issues. "
            "3) Apply senior-engineer improvements (architecture, patterns, efficiency). "
            "4) If time permits, implement the next high-priority enhancement. "
            "5) Run full verification."
        )
        refactor_first = True
    elif tier == EvolveTier.FOCUSED.value:
        resolved_goal = goal or FOCUS_GOALS.get(focus, FOCUS_GOALS["refactor"])
        refactor_first = focus == "refactor"
    else:
        resolved_goal = goal or "Choose the single highest-leverage safe improvement."
        refactor_first = False

    return EvolveWizardSession(
        tier=tier,
        focus=focus,
        goal=resolved_goal,
        duration=duration,
        passes=dur["passes"],
        timeout_seconds=dur["timeout_seconds"],
        promote_on_pass=promote_on_pass,
        refactor_first=refactor_first,
        confirmed=False,
        created_at=now,
    )
