"""Artifact proof helpers for the Exhaustive runtime."""

from __future__ import annotations

import re
from pathlib import Path

_NAMED_OUTPUT_RE = re.compile(r"(?<![\w./\\-])([A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.(?:csv|html|md|pdf|py|xlsx))\b", re.I)


def _artifact_evidence(prompt: str, work_dir: str) -> tuple[bool, list[str], list[str]]:
    """Read back nonempty workspace artifacts and enforce named/type expectations."""

    root = Path(work_dir)
    if not root.is_dir():
        return False, [], ["workspace_missing"]
    rows = [path for path in root.rglob("*") if path.is_file() and not any(part.startswith(".") for part in path.parts)]
    relative = {path.relative_to(root).as_posix().casefold(): path for path in rows}
    evidence = sorted(relative)
    issues: list[str] = []
    expected = {name.casefold() for name in _NAMED_OUTPUT_RE.findall(str(prompt or ""))}
    for name in sorted(expected):
        if name not in relative and not any(path.endswith("/" + name) for path in relative):
            issues.append(f"missing:{name}")
    lower = str(prompt or "").casefold()
    suffix_expectations = {
        ".pdf": "pdf",
        ".csv": "csv",
        ".xlsx": "spreadsheet",
        ".html": "website|game|html",
    }
    for suffix, token_pattern in suffix_expectations.items():
        if re.search(rf"\b(?:{token_pattern})\b", lower) and not any(name.endswith(suffix) for name in relative):
            issues.append(f"missing_type:{suffix}")
    for name, path in relative.items():
        try:
            if path.stat().st_size <= 0:
                issues.append(f"empty:{name}")
            elif name.endswith(".pdf") and not path.read_bytes().startswith(b"%PDF"):
                issues.append(f"invalid_pdf:{name}")
        except OSError:
            issues.append(f"unreadable:{name}")
    return bool(relative) and not issues, evidence, issues
