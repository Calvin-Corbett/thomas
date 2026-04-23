from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from thomas.demo.agentic_benchmark_endurance_server import isolated_thomas_server

__all__ = ["isolated_thomas_server"]

_SNAPSHOT_IGNORED_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".next",
    ".turbo",
    "node_modules",
    "tmp",
}

SNAPSHOT_IGNORED_PREFIXES = (
    "runtime/",
    "output/",
    "runtime/benchmarks/agentic-runs",
    "runtime/agentic_bench",
    "demo/agentic-runs",
    ".codex/background",
    ".playwright-mcp",
)

_SNAPSHOT_MAX_FILE_BYTES = 50 * 1024 * 1024


def _snapshot_ignore(src_root: Path, current_dir: str, names: list[str]) -> list[str]:
    rel = Path(current_dir).relative_to(src_root)
    ignored: list[str] = []
    for name in names:
        rel_path = (rel / name).as_posix()
        if name in _SNAPSHOT_IGNORED_NAMES:
            ignored.append(name)
            continue
        if any(rel_path == prefix.rstrip("/") or rel_path.startswith(prefix) for prefix in SNAPSHOT_IGNORED_PREFIXES):
            ignored.append(name)
            continue
        candidate = Path(current_dir) / name
        try:
            if candidate.is_file() and candidate.stat().st_size > _SNAPSHOT_MAX_FILE_BYTES:
                ignored.append(name)
        except OSError:
            continue
    return ignored


def copy_workspace_snapshot(src_root: Path, dst_root: Path) -> None:
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src_root,
        dst_root,
        ignore=lambda current_dir, names: _snapshot_ignore(src_root, current_dir, list(names)),
    )


def _reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server_ready(base_url: str, *, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    url = f"{base_url.rstrip('/')}/api/session/new"
    payload = json.dumps({}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                status = int(getattr(response, "status", 0) or 0)
                if 200 <= status < 500:
                    return
        except (urllib.error.URLError, OSError, TimeoutError, ConnectionError) as exc:
            last_error = str(exc)
            time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for Thomas API server at {base_url}: {last_error}")


def _git_lines(workspace_root: Path, *args: str, check: bool = True) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(workspace_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.splitlines()


def _status_paths(workspace_root: Path, ignored_prefixes: Sequence[str]) -> list[str]:
    changed: list[str] = []
    for raw in _git_lines(workspace_root, "status", "--porcelain=v1", "--untracked-files=all"):
        line = str(raw or "")
        if not line:
            continue
        path_text = line[3:]
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        normalized = path_text.replace("\\", "/").strip()
        if not normalized:
            continue
        if any(normalized.startswith(prefix) for prefix in ignored_prefixes):
            continue
        changed.append(normalized)
    return sorted(set(changed))


def _dirty_line_total(workspace_root: Path, ignored_prefixes: Sequence[str]) -> int:
    args = ["diff", "--numstat", "HEAD", "--"]
    for prefix in ignored_prefixes:
        args.append(f":(exclude){prefix}")
    total = 0
    for line in _git_lines(workspace_root, *args):
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            adds = 0 if parts[0] == "-" else int(parts[0])
            dels = 0 if parts[1] == "-" else int(parts[1])
        except ValueError:
            continue
        total += adds + dels
    return total


def capture_repo_snapshot(workspace_root: Path, ignored_prefixes: Sequence[str]) -> dict[str, Any]:
    head = "".join(_git_lines(workspace_root, "rev-parse", "HEAD")).strip()
    dirty_paths = _status_paths(workspace_root, ignored_prefixes)
    return {
        "head": head,
        "dirty_paths": dirty_paths,
        "dirty_file_count": len(dirty_paths),
        "dirty_line_total": _dirty_line_total(workspace_root, ignored_prefixes),
    }


async def monitor_repo_progress(
    workspace_root: Path,
    ignored_prefixes: Sequence[str],
    stop_event: asyncio.Event,
    *,
    poll_seconds: float = 5.0,
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    started = time.monotonic()
    while True:
        snapshot = capture_repo_snapshot(workspace_root, ignored_prefixes)
        timeline.append(
            {
                "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
                "head": str(snapshot.get("head") or ""),
                "dirty_file_count": int(snapshot.get("dirty_file_count") or 0),
                "dirty_line_total": int(snapshot.get("dirty_line_total") or 0),
            }
        )
        if stop_event.is_set():
            return timeline
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue


def timeline_summary(initial: Mapping[str, Any], timeline: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    initial_fingerprint = (
        str(initial.get("head") or ""),
        int(initial.get("dirty_file_count") or 0),
        int(initial.get("dirty_line_total") or 0),
    )
    first_progress: float | None = None
    first_commit: float | None = None
    previous: tuple[str, int, int] | None = None
    last_change_elapsed = 0.0
    stalls: list[float] = []

    for item in timeline:
        elapsed = float(item.get("elapsed_seconds") or 0.0)
        current = (
            str(item.get("head") or ""),
            int(item.get("dirty_file_count") or 0),
            int(item.get("dirty_line_total") or 0),
        )
        if first_progress is None and current != initial_fingerprint:
            first_progress = elapsed
        if first_commit is None and current[0] != initial_fingerprint[0]:
            first_commit = elapsed
        if previous is None:
            previous = current
            last_change_elapsed = elapsed
            continue
        if current == previous:
            continue
        unchanged_window = max(0.0, elapsed - last_change_elapsed)
        if unchanged_window >= 10.0:
            stalls.append(round(unchanged_window, 3))
        previous = current
        last_change_elapsed = elapsed

    return {
        "time_to_first_real_progress": first_progress,
        "time_to_first_commit": first_commit,
        "stall_count": len(stalls),
        "longest_stall_seconds": max(stalls) if stalls else 0.0,
    }


def new_commits(workspace_root: Path, initial_head: str) -> list[str]:
    if not initial_head:
        return []
    return [
        line.strip()
        for line in _git_lines(workspace_root, "rev-list", "--reverse", f"{initial_head}..HEAD")
        if line.strip()
    ]


def read_endurance_report(report_path: Path) -> dict[str, Any]:
    if not report_path.exists():
        return {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
