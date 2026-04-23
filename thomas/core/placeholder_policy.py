"""Utilities for detecting and validating placeholder-backed source files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER_MARKERS = (
    "source placeholder for",
    "size-matched placeholder",
    "python uses the cached .pyc",
)
REQUIRED_PLACEHOLDER_FIELDS = (
    "why",
    "scope_to_finish",
    "owner",
    "exit_rule",
    "acceptance",
)
_FIELD_RE = re.compile(
    r"^\s*(?:#|//|/\*+|\*|--)??\s*placeholder-(why|scope_to_finish|owner|exit_rule|acceptance)\s*:\s*(.+?)\s*(?:\*/)?\s*$",
    re.IGNORECASE,
)


def normalize_placeholder_path(raw: str) -> str:
    return str(raw or "").strip().replace("\\", "/")


def is_placeholder_text(text: str) -> bool:
    head = "\n".join(str(text or "").splitlines()[:6]).lower()
    return any(marker in head for marker in PLACEHOLDER_MARKERS)


def read_placeholder_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_placeholder_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in str(text or "").splitlines()[:24]:
        match = _FIELD_RE.match(raw_line)
        if not match:
            continue
        key = str(match.group(1) or "").strip().lower()
        value = str(match.group(2) or "").strip()
        if key and value and key not in fields:
            fields[key] = value
    return fields


def placeholder_policy_report(path: Path) -> dict[str, Any]:
    normalized = normalize_placeholder_path(str(path))
    if not path.exists() or (not path.is_file()):
        return {
            "path": normalized,
            "exists": False,
            "is_placeholder": False,
            "fields": {},
            "missing_fields": list(REQUIRED_PLACEHOLDER_FIELDS),
            "ok": False,
        }
    text = read_placeholder_text(path)
    is_placeholder = is_placeholder_text(text)
    fields = parse_placeholder_fields(text)
    missing = [field for field in REQUIRED_PLACEHOLDER_FIELDS if not fields.get(field)]
    return {
        "path": normalized,
        "exists": True,
        "is_placeholder": bool(is_placeholder),
        "fields": fields,
        "missing_fields": missing,
        "ok": (not is_placeholder) or (len(missing) == 0),
    }


def repo_relative_placeholder_path(path: Path, *, repo_root: Path | None = None) -> str:
    base = Path(repo_root or ROOT).resolve()
    target = Path(path).resolve()
    try:
        rel = target.relative_to(base)
    except ValueError:
        return normalize_placeholder_path(str(target))
    return normalize_placeholder_path(str(rel))
