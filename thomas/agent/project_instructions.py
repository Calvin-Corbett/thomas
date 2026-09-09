"""Project-scoped instruction discovery helpers.

This module is intentionally dependency-light because it is imported very early
in CLI/server startup paths.
"""

from __future__ import annotations

from pathlib import Path

from thomas.agent.instruction_resolution import (
    DEFAULT_MERGE_MAX_CHARS,
    INSTRUCTION_FILENAMES,
    resolve_merged_instructions,
)

# Fixed probe order shared with the hierarchical resolver: Thomas-native
# first, then imported formats (CLAUDE.md, AGENTS.md, .cursorrules).
_INSTRUCTION_FILENAMES: tuple[str, ...] = tuple(name for name, _fmt in INSTRUCTION_FILENAMES)


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


def discover_project_instructions(
    start: str | Path | None = None,
    *,
    max_chars: int = DEFAULT_MERGE_MAX_CHARS,
) -> str | None:
    """Resolve and merge all applicable instruction files for `start`.

    Walks from `start` up to the project root and merges every instruction
    file found (Thomas-native, CLAUDE.md, AGENTS.md, .cursorrules) with
    deterministic nearest-directory-wins precedence. See
    `thomas.agent.instruction_resolution` for the exact precedence contract.
    ``max_chars`` bounds the merged block so callers can respect their own
    prompt budget; lowest-precedence content is dropped first.
    """

    return resolve_merged_instructions(start, max_chars=max_chars)


def format_project_instructions(content: str) -> str:
    """Wrap instructions in explicit prompt delimiters for model clarity."""

    body = str(content or "").strip()
    if not body:
        return ""
    return "--- Project Instructions ---\n" + body + "\n--- End Project Instructions ---"
