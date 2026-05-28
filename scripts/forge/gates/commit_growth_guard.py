#!/usr/bin/env python3
"""Per-file growth guard for Thomas.

Prevents any single file from growing by more than MAX_GROWTH_LINES in a
single commit.  This is the key defense against agents that dump thousands
of lines into a file in one shot.

How it works:
  1. For every staged file, compute the line count in the working tree.
  2. Compute the line count at HEAD (or 0 if the file is new).
  3. If the growth exceeds the threshold, FAIL — unless the file extension
     is not in the monitored set.

Override:
  Set THOMAS_COMMIT_GROWTH_GUARD_DISABLE=1 to skip (audited by the
  pre-commit skip policy gate).

Exit codes:
  0 — all staged files within growth budget
  1 — one or more files exceed the per-commit growth cap
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
# ── Configurable limits ──────────────────────────────────────────────────
# Maximum net lines a single file may grow in one commit.
DEFAULT_MAX_GROWTH = 300
APPROVAL_TRAILERS = (
    "thomas-commit-growth-approved:",
    "thomas-growth-approved:",
    "thomas-breakglass:",
)
COMMIT_MESSAGE_ENV = "THOMAS_COMMIT_MESSAGE"

# File extensions to monitor.  Only these are checked.
MONITORED_EXTENSIONS: set[str] = {
    "py",
    "js",
    "mjs",
    "cjs",
    "jsx",
    "ts",
    "tsx",
    "css",
    "html",
}

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    "coverage",
    "runtime",
    "Inbox",
    "output",
    "pack",
    "patches",
    ".feature_backups",
}


def _runtime_protection_disabled() -> bool:
    """Check if a human has temporarily disabled runtime protection."""
    flag = ROOT / "runtime" / ".runtime_protection_disabled"
    return flag.is_file()


def _is_skipped(rel: str) -> bool:
    parts = Path(rel).parts
    return any(p in SKIP_DIR_NAMES for p in parts)


def _changed_files(repo_root: Path, *, base: str | None = None, head: str | None = None) -> list[str]:
    diff_args = ["git", "diff", "--name-only", "--diff-filter=ACMR"]
    if base and head:
        diff_args.extend([base, head])
    else:
        diff_args.append("--cached")
    proc = subprocess.run(
        diff_args,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _staged_files(repo_root: Path) -> list[str]:
    return _changed_files(repo_root)


def _commit_messages(repo_root: Path, base: str, head: str) -> list[str]:
    if base == head:
        return []
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%B%n---END---", f"{base}..{head}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [chunk.strip() for chunk in str(proc.stdout or "").split("---END---") if chunk.strip()]


def _growth_approval(messages: list[str]) -> tuple[bool, str, str]:
    for msg in messages:
        for line in msg.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            for trailer in APPROVAL_TRAILERS:
                if not lowered.startswith(trailer):
                    continue
                reason = stripped.split(":", 1)[1].strip()
                if reason:
                    return True, trailer.rstrip(":"), reason
    return False, "", ""


def _working_tree_lines(repo_root: Path, rel: str) -> int:
    path = repo_root / rel
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _head_lines(repo_root: Path, rel: str) -> int:
    """Line count of the file at HEAD.  Returns 0 for new files."""
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if proc.returncode != 0:
        return 0  # new file
    text = proc.stdout
    if not text:
        return 0
    return len(text.splitlines())


def _rev_lines(repo_root: Path, rev: str, rel: str) -> int:
    proc = subprocess.run(
        ["git", "show", f"{rev}:{rel}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if proc.returncode != 0 or not proc.stdout:
        return 0
    return len(proc.stdout.splitlines())


def run(
    repo_root: Path,
    *,
    max_growth: int = DEFAULT_MAX_GROWTH,
    json_output: bool = False,
    base: str | None = None,
    head: str | None = None,
) -> int:
    if _runtime_protection_disabled():
        if not json_output:
            print("Commit growth guard: PASS (runtime protection disabled by human)")
        return 0

    if os.environ.get("THOMAS_COMMIT_GROWTH_GUARD_DISABLE") == "1":
        if not json_output:
            print("Commit growth guard: SKIP (THOMAS_COMMIT_GROWTH_GUARD_DISABLE=1)")
        return 0

    staged = _changed_files(repo_root, base=base, head=head) if base and head else _staged_files(repo_root)
    violations: list[dict] = []
    approved = False
    approval_trailer = ""
    approval_reason = ""

    for rel in staged:
        if _is_skipped(rel):
            continue
        ext = Path(rel).suffix.lstrip(".").lower()
        if ext not in MONITORED_EXTENSIONS:
            continue

        if base and head:
            current = _rev_lines(repo_root, head, rel)
            prior = _rev_lines(repo_root, base, rel)
        else:
            current = _working_tree_lines(repo_root, rel)
            prior = _head_lines(repo_root, rel)
        growth = current - prior

        if growth > max_growth:
            violations.append(
                {
                    "path": rel,
                    "prior_lines": prior,
                    "current_lines": current,
                    "growth": growth,
                    "max_growth": max_growth,
                    "is_new_file": prior == 0,
                }
            )

    if violations and base and head:
        approved, approval_trailer, approval_reason = _growth_approval(_commit_messages(repo_root, base, head))
    elif violations:
        message = str(os.getenv(COMMIT_MESSAGE_ENV, "") or "")
        if message:
            approved, approval_trailer, approval_reason = _growth_approval([message])
    ok = len(violations) == 0 or approved

    if json_output:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "max_growth": max_growth,
                    "staged_count": len(staged),
                    "violations": violations,
                    "approved_growth": approved,
                    "approval_trailer": approval_trailer,
                    "approval_reason": approval_reason,
                },
                indent=2,
            )
        )
    elif ok:
        if approved:
            print(
                "Commit growth guard: PASS "
                f"({len(violations)} approved violation(s) via {approval_trailer}: {approval_reason[:120]})"
            )
        else:
            print(f"Commit growth guard: PASS (no file grew by more than {max_growth} lines)")
    else:
        print(
            f"Commit growth guard: FAIL — {len(violations)} file(s) "
            f"grew by more than {max_growth} lines in this commit."
        )
        print(
            f"  The per-commit growth cap is {max_growth} lines.  "
            f"Split your changes across multiple files or "
            f"multiple commits with meaningful intermediate states."
        )
        for v in violations:
            tag = " (NEW FILE)" if v["is_new_file"] else ""
            print(f"  - {v['path']}: {v['prior_lines']} -> {v['current_lines']} (+{v['growth']} lines){tag}")

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=("Block commits where any single file grows by too many lines."))
    parser.add_argument(
        "--max-growth",
        type=int,
        default=DEFAULT_MAX_GROWTH,
        help=f"Max net line growth per file (default: {DEFAULT_MAX_GROWTH}).",
    )
    parser.add_argument("--json", action="store_true", help="JSON output.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred).",
    )
    parser.add_argument("--base", default=None, help="Optional git base ref/SHA for diff-range mode.")
    parser.add_argument("--head", default=None, help="Optional git head ref/SHA for diff-range mode.")
    args = parser.parse_args()
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head must be provided together")

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    return run(repo_root, max_growth=args.max_growth, json_output=args.json, base=args.base, head=args.head)


if __name__ == "__main__":
    raise SystemExit(main())
