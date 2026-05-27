#!/usr/bin/env python3
"""AST-based scanner for pytest.mark.xfail markers.

Load-bearing module imported by:
- scripts/xfail_inventory.py (for the human-facing report tool)
- scripts/forge/gates/xfail_growth_gate.py (for BASE/HEAD count comparison)

Provides find_xfail_markers(rev=None) — returns one XfailEntry per
xfail discovered. The returned entries are MINIMAL (just file/line/scope/
reason) — enrichment (git blame, classification, arc-id) is done in
scripts/xfail_inventory.py to keep this module cheap.

count_at_rev(rev) is the cheap-count shortcut for the gate.

Why split from xfail_inventory.py: the inventory module would be ~395
lines and tripped the commit-growth-guard's 300-line cap for new files
(PROBLEM.md Specific findings #2). Separating the scanner from the
report-renderer is also good design — they're cohesive at the function
level (AST walking + identity vs reporting/enrichment), and the gate
benefits from importing only what it needs.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DIRS = ("tests", "thomas/tests")


@dataclass
class XfailEntry:
    """A single discovered xfail marker.

    Minimal at scan time. Enrichment fields (commit_*, arc_id, classification)
    are populated by scripts/xfail_inventory.py after scanning.
    """

    file: str
    line: int
    scope: str  # "module" | "function" | "param"
    reason: str
    commit_sha: str = ""
    commit_subject: str = ""
    commit_date: str = ""
    arc_id: str = ""
    classification: str = "other"

    def to_summary_row(self) -> str:
        return (
            f"{self.classification:14s}  {self.arc_id:14s}  {self.commit_date:10s}  "
            f"{self.file}:{self.line} ({self.scope})"
        )


def _is_xfail_call(node: ast.AST) -> bool:
    """True if `node` is a call to `pytest.mark.xfail(...)` or `xfail(...)`."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    # `pytest.mark.xfail`
    if isinstance(func, ast.Attribute) and func.attr == "xfail":
        parent = func.value
        if isinstance(parent, ast.Attribute) and parent.attr == "mark":
            return True
        if isinstance(parent, ast.Name) and parent.value == "mark":  # type: ignore[attr-defined]
            return True
    # Bare `xfail(...)`
    if isinstance(func, ast.Name) and func.id == "xfail":
        return True
    return False


def _extract_reason(call: ast.Call) -> str:
    """Pull the `reason=` kwarg text from a pytest.mark.xfail(...) call."""
    for kw in call.keywords:
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
        if kw.arg == "reason" and isinstance(kw.value, ast.JoinedStr):
            # f-string — best-effort literal extraction
            parts: list[str] = []
            for v in kw.value.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                else:
                    parts.append("<expr>")
            return "".join(parts)
    return ""


def _walk_tree_for_xfails(tree: ast.AST, file_label: str) -> list[XfailEntry]:
    """Walk a parsed AST and yield XfailEntry for every marker found."""
    entries: list[XfailEntry] = []
    for node in ast.walk(tree):
        # Module-level: `pytestmark = pytest.mark.xfail(...)`
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark" and _is_xfail_call(node.value):
                    entries.append(
                        XfailEntry(
                            file=file_label,
                            line=node.lineno,
                            scope="module",
                            reason=_extract_reason(node.value),  # type: ignore[arg-type]
                        )
                    )

        # Function-level: `@pytest.mark.xfail(...)` decorator
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for deco in node.decorator_list:
                if _is_xfail_call(deco):
                    entries.append(
                        XfailEntry(
                            file=file_label,
                            line=deco.lineno,
                            scope="function",
                            reason=_extract_reason(deco),  # type: ignore[arg-type]
                        )
                    )

        # Parametrize-level: `pytest.param(..., marks=pytest.mark.xfail(...))`
        if isinstance(node, ast.Call):
            func = node.func
            is_param = (isinstance(func, ast.Attribute) and func.attr == "param") or (
                isinstance(func, ast.Name) and func.id == "param"
            )
            if not is_param:
                continue
            for kw in node.keywords:
                if kw.arg != "marks":
                    continue
                if _is_xfail_call(kw.value):
                    entries.append(
                        XfailEntry(
                            file=file_label,
                            line=kw.value.lineno,  # type: ignore[union-attr]
                            scope="param",
                            reason=_extract_reason(kw.value),  # type: ignore[arg-type]
                        )
                    )

    return entries


def _find_xfails_in_file(path: Path) -> list[XfailEntry]:
    """AST-walk a test file on disk for every xfail marker."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return []
    rel_path = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    return _walk_tree_for_xfails(tree, rel_path)


def _find_xfails_at_rev(rev: str) -> list[XfailEntry]:
    """AST-walk every test file at a specific git revision."""
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", rev],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if proc.returncode != 0:
        return []
    entries: list[XfailEntry] = []
    for fname in proc.stdout.splitlines():
        if not any(fname.startswith(td) for td in TEST_DIRS):
            continue
        if not fname.endswith(".py"):
            continue
        show = subprocess.run(
            ["git", "show", f"{rev}:{fname}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if show.returncode != 0 or not show.stdout:
            continue
        try:
            tree = ast.parse(show.stdout, filename=fname)
        except (SyntaxError, ValueError, TypeError):
            continue
        entries.extend(_walk_tree_for_xfails(tree, fname))
    return entries


def find_xfail_markers(rev: str | None = None) -> list[XfailEntry]:
    """Discover all xfail markers at HEAD (rev=None) or at a given revision.

    Returns minimal XfailEntry (no enrichment). For human-facing reports
    that need git blame + classification + arc-id, use the enrich()
    function in scripts/xfail_inventory.py.
    """
    if rev is not None:
        return _find_xfails_at_rev(rev)

    # Working-tree scan.
    entries: list[XfailEntry] = []
    for test_dir in TEST_DIRS:
        root = REPO_ROOT / test_dir
        if not root.is_dir():
            continue
        for path in root.rglob("test_*.py"):
            entries.extend(_find_xfails_in_file(path))
    return entries


def count_at_rev(rev: str) -> int:
    """Cheap count-only path for the gate's BASE/HEAD comparison."""
    return len(find_xfail_markers(rev=rev))


if __name__ == "__main__":
    # Bare-minimum CLI for "how many xfails at HEAD" — for richer output
    # use scripts/xfail_inventory.py.
    entries = find_xfail_markers()
    print(f"{len(entries)} xfails across {len({e.file for e in entries})} files")
    sys.exit(0)
