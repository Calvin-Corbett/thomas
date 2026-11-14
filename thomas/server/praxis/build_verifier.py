"""Independent, bounded checks after a Build process has exited.

The verifier reads project files itself. It never executes a command from the
builder or mistakes a transcript assertion for a check result. Unsupported
checks produce no receipt, so acceptance remains unverified.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_MAX_CHECKS = 100
_MAX_READ_BYTES = 1_000_000


def verify_build_checks(
    project: Path, *, acceptance: list[dict[str, Any]], changed_files: list[str]
) -> list[dict[str, Any]]:
    root = project.resolve()
    changed = {str(path).replace("\\", "/").lstrip("/") for path in changed_files}
    receipts = []
    for check in acceptance[:_MAX_CHECKS]:
        if not isinstance(check, dict):
            continue
        kind = str(check.get("kind") or "")
        if kind not in {"file_exists", "file_contains"}:
            continue
        relative = str(check.get("path") or "").replace("\\", "/").lstrip("/")
        target = (root / relative).resolve()
        if not relative or relative not in changed or not target.is_relative_to(root) or not target.is_file():
            continue
        passed = True
        if kind == "file_contains":
            needle = str(check.get("needle") or "")
            if not needle or target.stat().st_size > _MAX_READ_BYTES:
                continue
            try:
                passed = needle in target.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
        receipts.append(
            {
                "check_id": str(check.get("id") or ""),
                "kind": kind,
                "source": "verifier",
                "status": "pass" if passed else "fail",
                "evidence_ref": relative,
                "covered_files": [relative],
            }
        )
    return receipts
