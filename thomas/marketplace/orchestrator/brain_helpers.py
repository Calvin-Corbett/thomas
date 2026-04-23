"""Helper functions for orchestrator brain routing/status behavior."""

from __future__ import annotations

import re
from typing import Any

_STATUS_FOLLOWUP_RE = (
    r"\b(?:status|progress|update|done yet|finished|still running|"
    r"what'?s happening|where are we|how(?:'s| is) (?:that|it|this|the task|the project|the background work) going)\b"
)
_BACKGROUND_REFERENCE_RE = r"\b(?:background|worker|delegat|parallel)\b"
_TOOLS_ROUTE_RE = re.compile(
    r"(?:\buse\s+(?:your\s+)?(?:file|files|tool|tools)\b|"
    r"\b(?:file|files|tool|tools)\b.*\b(?:repo|repository|workspace|folder|directory|path)\b|"
    r"\btop[- ]level\s+files?\b|"
    r"\bcurrent\s+(?:repo|repository|workspace)\b|"
    r"\bopen\s+https?://[^\s,\"')]+.*\b(?:headline|title|main\s+text)\b|"
    r"\b(?:shell|command|directory listing|list files)\b)",
    re.I,
)
_STRICT_OUTPUT_ONLY_RE = re.compile(
    r"(?:\b(?:answer|reply|respond|return)\s+with\s+only\b|"
    r"\bonly\s+the\s+exact\b|"
    r"\banswer\s+with\s+exactly\b|"
    r"\breply\s+with\s+exactly\b)",
    re.I,
)


def wants_background_status(prompt: str) -> bool:
    return bool(re.search(_STATUS_FOLLOWUP_RE, str(prompt or ""), re.I))


def should_answer_background_status_directly(prompt: str, active_tasks: list[dict[str, Any]] | None) -> bool:
    text = str(prompt or "").strip().lower()
    if not wants_background_status(text):
        return False
    if active_tasks:
        return True
    return bool(re.search(_BACKGROUND_REFERENCE_RE, text, re.I))


def summarize_background_status(active_tasks: list[dict[str, Any]] | None) -> str:
    rows = [dict(row or {}) for row in list(active_tasks or []) if isinstance(row, dict)]
    if not rows:
        return "No background work is running in this thread."

    active_rows: list[dict[str, Any]] = []
    completed_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    other_rows: list[dict[str, Any]] = []
    for row in rows:
        state = str(row.get("state") or "").strip().lower()
        if state in {"queued", "requested", "classified", "claimed", "executing", "running", "in_progress"}:
            active_rows.append(row)
        elif state == "completed":
            completed_rows.append(row)
        elif state in {"failed", "abandoned", "cancelled"}:
            failed_rows.append(row)
        else:
            other_rows.append(row)

    def _detail(row: dict[str, Any]) -> str:
        summary = str(row.get("summary") or "").strip()
        progress = str(row.get("last_progress") or "").strip()
        state = str(row.get("state") or "unknown").replace("_", " ").strip()
        if summary and progress and progress != summary:
            return f"{summary} ({state}: {progress})"
        if summary:
            return f"{summary} ({state})"
        if progress:
            return f"{progress} ({state})"
        return state

    if active_rows:
        lines = ["Background work is still running in this thread."]
        for row in active_rows[:2]:
            lines.append(f"- {_detail(row)}")
        return "\n".join(lines)

    if completed_rows and not failed_rows:
        lines = ["Background work has completed in this thread."]
        for row in completed_rows[:2]:
            lines.append(f"- {_detail(row)}")
        return "\n".join(lines)

    if failed_rows and not completed_rows:
        lines = ["Background work finished with issues in this thread."]
        for row in failed_rows[:2]:
            lines.append(f"- {_detail(row)}")
        return "\n".join(lines)

    lines = ["Background work in this thread has mixed outcomes."]
    for row in (active_rows + completed_rows + failed_rows + other_rows)[:3]:
        lines.append(f"- {_detail(row)}")
    return "\n".join(lines)


def is_deterministic_tools_route(prompt: str, available: list[str] | set[str] | tuple[str, ...]) -> bool:
    available_ids = {str(item or "").strip() for item in list(available or []) if str(item or "").strip()}
    prompt_text = str(prompt or "")
    return "tools" in available_ids and bool(_TOOLS_ROUTE_RE.search(prompt_text))


def should_suppress_actionable_ack(prompt: str, available: list[str] | set[str] | tuple[str, ...]) -> bool:
    return is_deterministic_tools_route(prompt, available) and bool(_STRICT_OUTPUT_ONLY_RE.search(str(prompt or "")))


def specialist_timeout_seconds(mode: str, token_economy: str) -> int:
    """Scale specialist timeout with explicit high-budget user intent."""
    normalized_mode = str(mode or "").strip().lower()
    normalized_economy = str(token_economy or "").strip().lower()
    if normalized_economy == "max":
        return 300
    if normalized_mode in {"thinking", "swarm", "max"}:
        return 240
    if normalized_mode == "fast":
        return 60
    return 120
