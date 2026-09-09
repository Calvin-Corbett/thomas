"""Report-only worktree triage: what exists, what is dirty, what would be lost.

Never deletes anything. Always exits 0 (a report that can block is a gate;
this is an instrument). Disposition 'removable' means provably nothing lost:
zero dirty files AND zero commits unreachable from dev.

If any git command needed to assess a worktree fails, that worktree's
disposition is forced to 'needs-review' -- a triage tool that cannot read a
worktree must never claim it is safe to delete.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_REPORT_ERRORS = (OSError, subprocess.SubprocessError, ValueError)


def _git(cwd: Path, *args: str) -> str | None:
    """Run git and return stdout, or None if the command failed.

    None is distinct from "" (a command that succeeded with no output, e.g. a
    clean `git status --porcelain`). Callers must not treat the two the same.
    """
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else None


def _has_venv_junction(venv: Path) -> bool:
    """True if `venv` is a symlink, or -- on Windows -- a directory junction.

    Path.is_symlink() returns False for real Windows junctions: a junction
    is a reparse point, not a symlink, and pathlib does not classify it as
    one (verified empirically on this machine: mklink /J then
    Path.is_symlink() -> False). os.path.isjunction() (Python 3.12+) is the
    correct check; guarded with hasattr so this module still imports on
    older Python versions or platforms without it.
    """
    if hasattr(os.path, "isjunction") and os.path.isjunction(str(venv)):
        return True
    return venv.is_symlink()


def _worktree_paths(repo_root: Path) -> tuple[list[tuple[Path, str]], bool]:
    """Returns (worktree pairs, listing_ok).

    listing_ok is False when the `git worktree list --porcelain` call itself
    failed -- distinct from a single worktree's per-row assessment failing,
    which triage() already tracks via each row's `assessment_failed` field.
    A listing failure means there ARE no rows to assess, not that there are
    zero worktrees; callers must not treat the two the same.
    """
    out = _git(repo_root, "worktree", "list", "--porcelain")
    if out is None:
        return [], False
    pairs: list[tuple[Path, str]] = []
    path, branch = None, ""
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :])
        elif line.startswith("branch "):
            branch = line[len("branch ") :].removeprefix("refs/heads/")
        elif not line:
            if path is not None:
                pairs.append((path, branch))
            path, branch = None, ""
    return pairs, True


def triage(repo_root: Path) -> list[dict]:
    rows: list[dict] = []
    paths, listing_ok = _worktree_paths(repo_root)
    if not listing_ok:
        print(
            "worktree listing FAILED - report is incomplete: "
            "`git worktree list --porcelain` did not succeed, so no worktree "
            "could be assessed. This is NOT a report of zero worktrees."
        )
        return rows
    for path, branch in paths:
        if path.resolve() == repo_root.resolve():
            continue  # the main checkout is not a triage candidate

        status_out = _git(path, "status", "--porcelain")
        head_out = _git(path, "rev-parse", "HEAD")
        head = head_out.strip() if head_out is not None else ""
        unique_out = _git(repo_root, "rev-list", f"dev..{head}") if head else ""
        last_out = _git(path, "log", "-1", "--format=%cs")

        assessment_failed = any(v is None for v in (status_out, head_out, unique_out, last_out))

        dirty = len(status_out.splitlines()) if status_out else 0
        unique = len(unique_out.splitlines()) if unique_out else 0
        last = last_out.strip() if last_out else ""

        has_junction = _has_venv_junction(path / ".venv")

        if assessment_failed:
            disposition = "needs-review"
        else:
            disposition = "removable" if dirty == 0 and unique == 0 else "needs-review"

        rows.append(
            {
                "path": str(path),
                "branch": branch,
                "dirty_files": dirty,
                "unique_commits": unique,
                "last_commit_date": last,
                "has_venv_junction": bool(has_junction),
                "assessment_failed": assessment_failed,
                "disposition": disposition,
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()
    try:
        rows = triage(ns.repo_root)
    except _REPORT_ERRORS as exc:
        print(f"triage report incomplete: {exc}")
        return 0
    if ns.json:
        print(json.dumps(rows, indent=1))
        return 0
    print(
        "| worktree | branch | dirty | unique commits | last commit | venv-junction | assessment-failed | disposition |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {Path(r['path']).name} | {r['branch']} | {r['dirty_files']} "
            f"| {r['unique_commits']} | {r['last_commit_date']} "
            f"| {'YES' if r['has_venv_junction'] else 'no'} "
            f"| {'YES' if r['assessment_failed'] else 'no'} | {r['disposition']} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
