"""Continuously audit the repository for stale TODO-style markers.

The watcher scans tracked text files for TODO/FIXME/XXX comments, uses git blame
metadata to estimate marker age, and writes rolling reports until stopped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.watch_stale_todos_reporting import (
        append_log,
        fingerprint,
        markdown_report,
        report_payload,
        write_text,
    )
except ImportError:
    from watch_stale_todos_reporting import (  # type: ignore
        append_log,
        fingerprint,
        markdown_report,
        report_payload,
        write_text,
    )
try:
    from scripts.watch_stale_todos_types import TodoMarker
except ImportError:
    from watch_stale_todos_types import TodoMarker  # type: ignore

MARKER_RE = re.compile(r"\b(TODO|FIXME|XXX)\b")
SKIP_SUFFIXES = {
    ".lock",
    ".min.js",
    ".min.css",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".db",
    ".woff",
    ".woff2",
    ".ttf",
}
SKIP_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
}

def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _iter_tracked_files(repo_root: Path) -> list[str]:
    proc = _run_git(repo_root, "ls-files")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git ls-files failed")
    files: list[str] = []
    for raw in proc.stdout.splitlines():
        rel = raw.strip()
        if not rel:
            continue
        path = Path(rel)
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        rel_lower = rel.lower()
        if any(rel_lower.endswith(suffix) for suffix in SKIP_SUFFIXES):
            continue
        files.append(rel)
    return files


def _grep_marker_lines(repo_root: Path) -> dict[str, list[tuple[int, str]]]:
    proc = _run_git(repo_root, "grep", "-nI", "-E", MARKER_RE.pattern, "--")
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr.strip() or "git grep failed")
    matches: dict[str, list[tuple[int, str]]] = {}
    for raw in proc.stdout.splitlines():
        rel_path, sep, remainder = raw.partition(":")
        if not sep:
            continue
        line_no_text, sep, text = remainder.partition(":")
        if not sep:
            continue
        rel = rel_path.strip()
        if not rel:
            continue
        path_obj = Path(rel)
        if any(part in SKIP_PARTS for part in path_obj.parts):
            continue
        rel_lower = rel.lower()
        if any(rel_lower.endswith(suffix) for suffix in SKIP_SUFFIXES):
            continue
        try:
            line_no = int(line_no_text)
        except ValueError:
            continue
        matches.setdefault(rel, []).append((line_no, text.strip()))
    return matches


def _load_text(path: Path) -> list[str] | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return None
    if "\x00" in raw:
        return None
    return raw.splitlines()


def _git_datetime(unix_seconds: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(unix_seconds), UTC)
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _parse_blame(stdout: str) -> dict[int, dict[str, Any]]:
    lines = stdout.splitlines()
    result: dict[int, dict[str, Any]] = {}
    idx = 0
    final_line = 0
    current_commit = ""
    current_author = ""
    current_time: datetime | None = None

    while idx < len(lines):
        header = lines[idx]
        idx += 1
        if not header:
            continue
        parts = header.split()
        if len(parts) < 3:
            continue
        current_commit = parts[0]
        try:
            final_line = int(parts[2])
            group_count = int(parts[3]) if len(parts) > 3 else 1
        except ValueError:
            continue

        while idx < len(lines):
            meta = lines[idx]
            idx += 1
            if meta.startswith("\t"):
                for offset in range(group_count):
                    result[final_line + offset] = {
                        "commit": current_commit,
                        "author": current_author,
                        "committed_at": current_time,
                    }
                break
            if meta.startswith("author "):
                current_author = meta[7:].strip()
            elif meta.startswith("author-time "):
                current_time = _git_datetime(meta[12:].strip())
    return result


def _blame_for_file(repo_root: Path, rel_path: str) -> dict[int, dict[str, Any]]:
    proc = _run_git(repo_root, "blame", "--line-porcelain", "--", rel_path)
    if proc.returncode != 0:
        return {}
    return _parse_blame(proc.stdout)


def _find_markers(repo_root: Path, stale_days: int) -> list[TodoMarker]:
    now = datetime.now(UTC)
    markers: list[TodoMarker] = []
    for rel_path, matching_rows in _grep_marker_lines(repo_root).items():
        blame_map = _blame_for_file(repo_root, rel_path)
        for line_no, text in matching_rows:
            match = MARKER_RE.search(text)
            blame = blame_map.get(line_no, {})
            committed_at = blame.get("committed_at")
            age_days = None
            if isinstance(committed_at, datetime):
                age_days = max(0, int((now - committed_at).total_seconds() // 86400))
            markers.append(
                TodoMarker(
                    path=rel_path,
                    line=line_no,
                    kind=(match.group(1) if match else "TODO").upper(),
                    text=text[:240],
                    author=str(blame.get("author") or "unknown"),
                    commit=str(blame.get("commit") or ""),
                    committed_at=committed_at,
                    age_days=age_days,
                    stale=age_days is not None and age_days >= stale_days,
                )
            )
    markers.sort(
        key=lambda row: (
            0 if row.stale else 1,
            -(row.age_days or -1),
            row.path,
            row.line,
        )
    )
    return markers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Continuously audit the repo for stale TODO-style markers.")
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    parser.add_argument("--interval-seconds", type=float, default=900.0, help="Polling interval in seconds.")
    parser.add_argument("--stale-days", type=int, default=45, help="Age threshold for stale TODO markers.")
    parser.add_argument("--json-out", default=".codex/background/stale_todo_audit.json")
    parser.add_argument("--md-out", default=".codex/background/stale_todo_audit.md")
    parser.add_argument("--log-out", default=".codex/background/stale_todo_audit.log")
    parser.add_argument("--pid-out", default=".codex/background/stale_todo_audit.pid")
    parser.add_argument("--once", action="store_true", help="Run one audit and exit.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).expanduser().resolve()
    if not (repo_root / ".git").exists():
        print(f"not a git repo: {repo_root}", file=sys.stderr)
        return 2

    interval = max(30.0, float(args.interval_seconds))
    stale_days = max(1, int(args.stale_days))
    json_out = (repo_root / args.json_out).resolve()
    md_out = (repo_root / args.md_out).resolve()
    log_out = (repo_root / args.log_out).resolve()
    pid_out = (repo_root / args.pid_out).resolve()
    write_text(pid_out, str(os.getpid()) + "\n")

    last_fingerprint = ""
    while True:
        started = time.time()
        try:
            markers = _find_markers(repo_root, stale_days=stale_days)
            payload = report_payload(repo_root, markers, stale_days=stale_days)
            write_text(json_out, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            write_text(md_out, markdown_report(payload))
            current_fingerprint = fingerprint(payload)
            stamp = datetime.now(UTC).isoformat()
            totals = payload.get("totals", {})
            if current_fingerprint != last_fingerprint:
                append_log(
                    log_out,
                    (
                        f"[{stamp}] change detected "
                        f"markers={totals.get('markers', 0)} "
                        f"stale={totals.get('stale_markers', 0)} "
                        f"files={totals.get('files_with_stale_markers', 0)}"
                    ),
                )
                last_fingerprint = current_fingerprint
            else:
                append_log(
                    log_out,
                    (
                        f"[{stamp}] heartbeat "
                        f"markers={totals.get('markers', 0)} "
                        f"stale={totals.get('stale_markers', 0)}"
                    ),
                )
        except KeyboardInterrupt:
            append_log(log_out, f"[{datetime.now(UTC).isoformat()}] stopped")
            return 0
        except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError) as exc:
            append_log(log_out, f"[{datetime.now(UTC).isoformat()}] error: {exc}")
            if args.once:
                raise
        if args.once:
            return 0
        elapsed = time.time() - started
        time.sleep(max(5.0, interval - elapsed))


if __name__ == "__main__":
    raise SystemExit(main())
