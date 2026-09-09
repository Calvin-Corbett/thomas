"""Canonical task-type taxonomy.

Shared source of truth for the task router (Step 2) and the verifier (Step 6),
so verification dispatch and team selection agree on one set of task types
instead of each hardcoding its own strings.
"""

from __future__ import annotations

from enum import Enum


class TaskType(str, Enum):
    BUILD_FEATURE = "build-feature"
    FIX_BUG = "fix-bug"
    CODE_REVIEW = "code-review"
    REFACTOR = "refactor-code"
    RESEARCH = "research-topic"
    ANALYZE_DATA = "analyze-data"
    WRITE_DOCS = "write-docs"
    DEPLOY = "deploy-software"
    DESIGN_UI = "design-ui"
    SECURITY_AUDIT = "security-audit"
    QUICK_FIX = "quick-fix"
    GENERAL = "general"  # fallback when nothing matches


ALL_TASK_TYPES: tuple[str, ...] = tuple(t.value for t in TaskType)

# Coarse family per task type — drives which verifier runs (Step 6).
# code | research | data | ui | docs | ops | general
TASK_FAMILY: dict[str, str] = {
    "build-feature": "code",
    "fix-bug": "code",
    "code-review": "code",
    "refactor-code": "code",
    "quick-fix": "code",
    "security-audit": "code",
    "research-topic": "research",
    "analyze-data": "data",
    "design-ui": "ui",
    "write-docs": "docs",
    "deploy-software": "ops",
    "general": "general",
}


def coerce_task_type(value: object) -> TaskType:
    """Best-effort map a string (value or NAME) to a TaskType; GENERAL on miss."""
    raw = str(value or "").strip().lower()
    for t in TaskType:
        if t.value == raw or t.name.lower() == raw:
            return t
    return TaskType.GENERAL


def task_family(value: object) -> str:
    """Return the coarse verifier family for a task type."""
    return TASK_FAMILY.get(coerce_task_type(value).value, "general")
