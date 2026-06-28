"""Shared private marker parsing for public publish tools."""

from __future__ import annotations

import re
from pathlib import Path

__all__ = (
    "ACCEPTED_PRIVATE_MARKER_LINES",
    "DEFAULT_MAX_SCAN_BYTES",
    "MARKER_REFERENCE_PATHS",
    "PRIVATE_MARKER",
    "is_marker_reference_path",
    "line_has_private_marker",
    "path_has_private_marker",
)

PRIVATE_MARKER = "THOMAS_PRIVATE"
DEFAULT_MAX_SCAN_BYTES = 2_000_000
ACCEPTED_PRIVATE_MARKER_LINES = frozenset(
    {
        PRIVATE_MARKER,
        f"# {PRIVATE_MARKER}",
        f"// {PRIVATE_MARKER}",
        f"/* {PRIVATE_MARKER} */",
        f"<!-- {PRIVATE_MARKER} -->",
    }
)
MARKER_REFERENCE_PATHS = frozenset(
    {
        "docs/trash_marker.md",
    }
)


def line_has_private_marker(line: str) -> bool:
    return line.strip() in ACCEPTED_PRIVATE_MARKER_LINES


def _normalize_reference_path(path: str | Path) -> str:
    normalized = re.sub(r"/{2,}", "/", str(path or "").strip().replace("\\", "/"))
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_marker_reference_path(path: str | Path) -> bool:
    return _normalize_reference_path(path) in MARKER_REFERENCE_PATHS


def path_has_private_marker(
    repo_root: Path,
    rel_path: str | Path,
    *,
    max_scan_bytes: int = DEFAULT_MAX_SCAN_BYTES,
) -> bool:
    """Return true when an in-repo file contains an exact private marker line.

    Marker convention docs are exempt, paths escaping ``repo_root`` are ignored,
    and oversized or unreadable files fail closed as not privately marked.
    """
    normalized = _normalize_reference_path(rel_path)
    if not normalized or is_marker_reference_path(normalized):
        return False
    try:
        root = repo_root.resolve()
        full_path = (root / normalized).resolve()
        if root != full_path and root not in full_path.parents:
            return False
        if is_marker_reference_path(full_path.relative_to(root)):
            return False
        if not full_path.exists() or not full_path.is_file():
            return False
        if full_path.stat().st_size > max_scan_bytes:
            return False
        text = full_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(line_has_private_marker(line) for line in text.splitlines())
