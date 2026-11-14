#!/usr/bin/env python3
"""Check that staged changes under plans/thomas/archive/ only ever append. stdlib only.

    python scripts/praxis/archive_append_only.py            # exit 1 and list violations

The claim gates let anyone stage files under the archive folder without a claim, and the change budget
does not count them, so nothing else stops an edit or a delete of archived rows. This check is the rule
that makes the waiver safe. A staged path under the folder passes only when ALL of these hold:

  - its name is exactly messages-YYYY-MM.txt, directly in the folder (no other file type, no subfolder)
  - it is added, or modified so that the committed bytes are an unchanged prefix of the staged bytes
  - it is never deleted or renamed

It is not wired into any gate: it is a candidate for the owner to adopt (see REPORT2.json).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ARCHIVE_DIR = "plans/thomas/archive/"
ARCHIVE_NAME = re.compile(r"plans/thomas/archive/messages-\d{4}-(0[1-9]|1[0-2])\.txt")


def check_change(path: str, status: str, old: bytes | None, new: bytes | None) -> list[str]:
    """Violations for one staged path (empty list = fine)."""
    if not ARCHIVE_NAME.fullmatch(path):
        return [f"{path}: only plans/thomas/archive/messages-YYYY-MM.txt may live under the archive folder"]
    if status == "A":
        return []
    if status != "M":
        return [f"{path}: archive files may only be added or appended to (status {status})"]
    if old is None or new is None:
        return [f"{path}: could not read the committed and staged bytes to compare"]
    if len(new) <= len(old) or not new.startswith(old):
        return [f"{path}: archived bytes were changed, not just appended to"]
    return []


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, timeout=30)


def _blob(root: Path, spec: str) -> bytes | None:
    proc = _git(root, "show", spec)
    return proc.stdout if proc.returncode == 0 else None


def staged_violations(root: Path) -> list[str]:
    """Violations in the index of ``root`` compared with HEAD."""
    proc = _git(root, "diff", "--cached", "--name-status", "--no-renames", "-z", "--", ARCHIVE_DIR)
    if proc.returncode != 0:
        return [f"git diff --cached failed: {proc.stderr.decode('utf-8', 'replace').strip()}"]
    fields = [f.decode("utf-8", "replace") for f in proc.stdout.split(b"\0") if f]
    violations: list[str] = []
    for status, path in zip(fields[0::2], fields[1::2], strict=False):
        old = _blob(root, f"HEAD:{path}") if status == "M" else None
        new = _blob(root, f":{path}") if status == "M" else None
        violations += check_change(path, status[:1], old, new)
    return violations


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[2]
    problems = staged_violations(root)
    for line in problems:
        print(f"archive append-only check: {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
