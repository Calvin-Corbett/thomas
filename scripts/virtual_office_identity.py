"""Identity helpers used by workboard orchestration scripts.

These helpers intentionally provide deterministic display names for agent IDs when
claims/tasks need a human-friendly label.
"""

from __future__ import annotations

import re


def default_display_name(agent: str | None) -> str:
    """Return a human-friendly fallback name for an agent identifier.

    The workboard helpers use this when a display name is not provided by caller.
    """
    raw = str(agent or "").strip()
    if not raw:
        return "Thomas Agent"

    # Normalize common separators to spaces and collapse extra whitespace.
    normalized = re.sub(r"[-_]+", " ", raw)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # Preserve short numeric tokens while title-casing words.
    parts = [part for part in normalized.split(" ") if part]
    if not parts:
        return "Thomas Agent"

    return " ".join(part.capitalize() if not part.isdigit() else part for part in parts)
