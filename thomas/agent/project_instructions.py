"""Project-scoped instruction discovery helpers.

This module is intentionally dependency-light because it is imported very early
in CLI/server startup paths.
"""

from __future__ import annotations

from pathlib import Path

_INSTRUCTION_FILENAMES: tuple[str, ...] = ("THOMAS.md", ".thomas.md")


def _as_start_dir(start: str | Path | None) -> Path:
    base = Path(start) if start else Path.cwd()
    try:
        resolved = base.expanduser().resolve()
    except OSError:
        resolved = base.expanduser()
    return resolved.parent if resolved.is_file() else resolved


def instruction_file_path(start: str | Path | None = None) -> Path | None:
    """Return the nearest project instruction file from `start` upward."""

    cursor = _as_start_dir(start)
    for parent in (cursor, *cursor.parents):
        for filename in _INSTRUCTION_FILENAMES:
            candidate = parent / filename
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def discover_project_instructions(start: str | Path | None = None) -> str | None:
    """Load project instruction text from the nearest instruction file."""

    path = instruction_file_path(start)
    if not path:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None


def format_project_instructions(content: str) -> str:
    """Wrap instructions in explicit prompt delimiters for model clarity."""

    body = str(content or "").strip()
    if not body:
        return ""
    return "--- Project Instructions ---\n" + body + "\n--- End Project Instructions ---"
