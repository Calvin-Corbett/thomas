"""Live monolith guard watcher for local edit sessions.

Polls changed/untracked files and prints warnings as soon as any file exceeds
the monolith guard thresholds (hard limit, soft limit, or baseline max_lines).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT_FALLBACK = SCRIPT_DIR.parent
if str(REPO_ROOT_FALLBACK) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_FALLBACK))

from scripts.check_monolith_guard import (
    DEFAULT_BASELINE,
    DEFAULT_HARD_LIMITS,
    DEFAULT_SCAN_ROOTS,
    load_baseline,
)


def _normalize_rel_path(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _run_git(repo_root: Path, args: Iterable[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *list(args)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _git_changed_worktree_files(repo_root: Path) -> set[str]:
    out: set[str] = set()
    commands = (
        ("diff", "--name-only"),
        ("diff", "--name-only", "--cached"),
        ("ls-files", "--others", "--exclude-standard"),
    )
    for cmd in commands:
        proc = _run_git(repo_root, cmd)
        if proc.returncode != 0:
            continue
        for raw in proc.stdout.splitlines():
            rel = _normalize_rel_path(raw)
            if rel:
                out.add(rel)
    return out


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def _is_under_scan_roots(rel_path: str, scan_roots: Iterable[str]) -> bool:
    rel = _normalize_rel_path(rel_path)
    if not rel:
        return False
    for root in scan_roots:
        root_norm = _normalize_rel_path(root).rstrip("/")
        if not root_norm:
            continue
        if rel == root_norm or rel.startswith(root_norm + "/"):
            return True
    return False


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _build_limits(baseline: dict[str, Any]) -> tuple[dict[str, int], list[str], dict[str, dict[str, Any]], int]:
    hard_limits = dict(DEFAULT_HARD_LIMITS)
    baseline_limits = baseline.get("hard_limits")
    if isinstance(baseline_limits, dict):
        for key, value in baseline_limits.items():
            hard_limits[str(key)] = _coerce_int(value, hard_limits.get(str(key), 0))

    scan_roots = list(DEFAULT_SCAN_ROOTS)
    baseline_scan_roots = baseline.get("scan_roots")
    if isinstance(baseline_scan_roots, list):
        rows = [str(x).strip() for x in baseline_scan_roots if str(x).strip()]
        if rows:
            scan_roots = rows

    allowed_large_files: dict[str, dict[str, Any]] = {}
    allowed_raw = baseline.get("allowed_large_files")
    if isinstance(allowed_raw, dict):
        for key, row in allowed_raw.items():
            if not isinstance(row, dict):
                continue
            allowed_large_files[_normalize_rel_path(str(key))] = row

    waiver_policy = baseline.get("waiver_policy")
    soft_limit = 0
    if isinstance(waiver_policy, dict):
        soft_limit = max(0, _coerce_int(waiver_policy.get("unbaselined_soft_limit_lines", 0), 0))

    return hard_limits, scan_roots, allowed_large_files, soft_limit


def _check_changed_files(
    repo_root: Path,
    baseline_path: Path,
    *,
    include_soft_limit: bool,
) -> list[dict[str, Any]]:
    baseline = load_baseline(baseline_path)
    hard_limits, scan_roots, allowed_large_files, soft_limit = _build_limits(baseline)
    changed_files = _git_changed_worktree_files(repo_root)

    violations: list[dict[str, Any]] = []
    for rel in sorted(changed_files):
        if not _is_under_scan_roots(rel, scan_roots):
            continue
        ext = Path(rel).suffix.lower().lstrip(".")
        if ext not in hard_limits:
            continue

        abs_path = repo_root / rel
        if not abs_path.exists() or not abs_path.is_file():
            continue

        lines = _line_count(abs_path)
        hard = int(hard_limits.get(ext, 0) or 0)
        allow = allowed_large_files.get(rel)

        if isinstance(allow, dict):
            max_lines = _coerce_int(allow.get("max_lines", hard), hard)
            if lines > max_lines:
                violations.append(
                    {
                        "path": rel,
                        "lines": lines,
                        "hard_limit": hard,
                        "max_lines": max_lines,
                        "reason": "baselined file exceeded max_lines",
                    }
                )
            continue

        if lines > hard:
            violations.append(
                {
                    "path": rel,
                    "lines": lines,
                    "hard_limit": hard,
                    "reason": "file exceeds hard limit and is not baselined",
                }
            )
            continue

        if include_soft_limit and soft_limit > 0 and lines > soft_limit:
            violations.append(
                {
                    "path": rel,
                    "lines": lines,
                    "hard_limit": hard,
                    "soft_limit": soft_limit,
                    "reason": "changed file exceeds soft limit and is not baselined",
                }
            )

    return violations


def _fingerprint(violations: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
    rows: list[tuple[Any, ...]] = []
    for row in violations:
        rows.append(
            (
                str(row.get("path", "")),
                int(row.get("lines", 0) or 0),
                int(row.get("hard_limit", 0) or 0),
                int(row.get("max_lines", 0) or 0),
                int(row.get("soft_limit", 0) or 0),
                str(row.get("reason", "")),
            )
        )
    rows.sort()
    return tuple(rows)


def _print_warnings(violations: list[dict[str, Any]]) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[monolith-watch] {stamp} WARNING: {len(violations)} issue(s) detected.", flush=True)
    for row in violations:
        path = str(row.get("path", ""))
        lines = int(row.get("lines", 0) or 0)
        hard = int(row.get("hard_limit", 0) or 0)
        max_lines = int(row.get("max_lines", 0) or 0)
        soft = int(row.get("soft_limit", 0) or 0)
        reason = str(row.get("reason", ""))
        extras: list[str] = [f"hard={hard}"]
        if max_lines:
            extras.append(f"max={max_lines}")
        if soft:
            extras.append(f"soft={soft}")
        print(f"  - {path}: {lines} lines ({', '.join(extras)}) -> {reason}", flush=True)


def _print_clear() -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[monolith-watch] {stamp} OK: no monolith issues in changed files.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch changed files and warn on monolith guard violations.")
    parser.add_argument("--repo-root", default=".", help="Repository root path (default: current directory).")
    parser.add_argument(
        "--baseline", default=DEFAULT_BASELINE, help=f"Baseline JSON path (default: {DEFAULT_BASELINE})."
    )
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds (default: 2.0).")
    parser.add_argument(
        "--include-soft-limit",
        action="store_true",
        help="Also warn when changed files exceed the unbaselined soft limit.",
    )
    parser.add_argument("--once", action="store_true", help="Run one check and exit with non-zero on violations.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = (repo_root / baseline_path).resolve()
    interval = max(0.5, float(args.interval))

    if not (repo_root / ".git").exists():
        print(f"[monolith-watch] ERROR: not a git repo: {repo_root}", file=sys.stderr, flush=True)
        return 2

    if args.once:
        violations = _check_changed_files(
            repo_root,
            baseline_path,
            include_soft_limit=bool(args.include_soft_limit),
        )
        if violations:
            _print_warnings(violations)
            return 1
        _print_clear()
        return 0

    print(
        f"[monolith-watch] watching changed files every {interval:.1f}s "
        f"(repo={repo_root}, baseline={baseline_path})",
        flush=True,
    )

    last = None
    while True:
        try:
            violations = _check_changed_files(
                repo_root,
                baseline_path,
                include_soft_limit=bool(args.include_soft_limit),
            )
            current = _fingerprint(violations)
            if current != last:
                if violations:
                    _print_warnings(violations)
                else:
                    _print_clear()
                last = current
            time.sleep(interval)
        except KeyboardInterrupt:
            print("[monolith-watch] stopped.", flush=True)
            return 0
        except Exception as exc:
            print(f"[monolith-watch] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
