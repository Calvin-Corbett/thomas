"""Runtime guard functions for Thomas server."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas import __version__ as THOMAS_VERSION
from thomas.core.config import AppConfig
from thomas.server.app_keys import APP_RUNTIME_GUARD_STATE

from .app_helpers import _resolve_app_value, _resolve_runtime_config

if TYPE_CHECKING:
    from aiohttp import web

log = logging.getLogger(__name__)


def _runtime_guard_iso_now() -> str:
    """Return current UTC time in ISO format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _runtime_guard_run_git(repo_root: Path, *args: str) -> tuple[bool, str]:
    """Run a git command and return (success, output)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        return False, err or f"exit {result.returncode}"
    return True, (result.stdout or "").strip()


def _runtime_guard_find_repo_root() -> Path | None:
    """Find the git repository root."""
    candidates = [Path.cwd(), Path(__file__).resolve().parents[2]]
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate.resolve())
        if marker in seen:
            continue
        seen.add(marker)
        ok, out = _runtime_guard_run_git(candidate, "rev-parse", "--show-toplevel")
        if not ok:
            continue
        try:
            repo_root = Path(out.strip()).resolve()
        except (OSError, ValueError):
            continue
        if repo_root.exists():
            return repo_root
    return None


def _runtime_guard_read_lock_info(config: AppConfig) -> dict[str, Any]:
    """Read the serve.lock file if it exists."""
    lock_file = Path(config.memory.root_path) / ".thomas" / "serve.lock"
    if not lock_file.exists():
        return {"exists": False, "path": str(lock_file)}
    try:
        payload = json.loads(lock_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
        payload = dict(payload)
        payload["exists"] = True
        payload["path"] = str(lock_file)
        return payload
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "exists": True,
            "path": str(lock_file),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _runtime_guard_collect_source_snapshot(repo_root: Path | None) -> dict[str, Any]:
    """Collect source code state snapshot."""
    snapshot: dict[str, Any] = {
        "repo_available": False,
        "repo_root": "",
        "git_branch": "",
        "git_head": "",
        "tracked_worktree_digest": "",
        "tracked_change_count": 0,
        "tracked_worktree_dirty": False,
        "errors": [],
    }
    if repo_root is None:
        return snapshot

    snapshot["repo_available"] = True
    snapshot["repo_root"] = str(repo_root)

    ok_head, head_out = _runtime_guard_run_git(repo_root, "rev-parse", "HEAD")
    if ok_head:
        snapshot["git_head"] = head_out
    else:
        snapshot["errors"].append(f"git_head: {head_out}")

    ok_branch, branch_out = _runtime_guard_run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    if ok_branch:
        snapshot["git_branch"] = branch_out
    else:
        snapshot["errors"].append(f"git_branch: {branch_out}")

    ok_status, status_out = _runtime_guard_run_git(
        repo_root,
        "status",
        "--porcelain",
        "--untracked-files=no",
    )
    if ok_status:
        rows = [row.rstrip() for row in status_out.splitlines() if row.strip()]
        normalized = "\n".join(rows)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""
        snapshot["tracked_worktree_digest"] = digest
        snapshot["tracked_change_count"] = len(rows)
        snapshot["tracked_worktree_dirty"] = bool(rows)
    else:
        snapshot["errors"].append(f"git_status: {status_out}")

    return snapshot


def _runtime_guard_boot_state(config: AppConfig) -> dict[str, Any]:
    """Initialize the runtime guard boot state."""
    try:
        interval_s = float(os.environ.get("THOMAS_RUNTIME_GUARD_INTERVAL_S", "45"))
    except (ValueError, TypeError):
        interval_s = 45.0
    interval_s = max(10.0, min(300.0, interval_s))

    repo_root = _runtime_guard_find_repo_root()
    source_snapshot = _runtime_guard_collect_source_snapshot(repo_root)
    lock_snapshot = _runtime_guard_read_lock_info(config)

    return {
        "enabled": True,
        "check_interval_s": interval_s,
        "boot": {
            "pid": os.getpid(),
            "version": THOMAS_VERSION,
            "booted_at_utc": _runtime_guard_iso_now(),
            "source": source_snapshot,
            "lock": lock_snapshot,
        },
        "status": {
            "checked_at_utc": "",
            "is_latest_code": True,
            "state": "ok",
            "reasons": [],
            "alert_message": "",
        },
        "current": {},
    }


def _runtime_guard_refresh(app: web.Application) -> dict[str, Any]:
    """Refresh runtime guard state and detect staleness."""
    cfg = _resolve_runtime_config(app)
    state = _resolve_app_value(app, APP_RUNTIME_GUARD_STATE, expected_type=dict, required=True)
    boot = dict(state.get("boot") or {})

    boot_source = dict(boot.get("source") or {})
    repo_root_raw = str(boot_source.get("repo_root") or "").strip()
    repo_root = Path(repo_root_raw) if repo_root_raw else None
    source_snapshot = _runtime_guard_collect_source_snapshot(repo_root)
    lock_snapshot = _runtime_guard_read_lock_info(cfg)

    reasons: list[str] = []
    lock_pid = lock_snapshot.get("pid")
    try:
        lock_pid_int = int(lock_pid)
    except (ValueError, TypeError):
        lock_pid_int = None
    if lock_pid_int is None:
        reasons.append("serve_lock_missing_or_invalid")
    elif lock_pid_int != os.getpid():
        reasons.append("serve_lock_points_to_other_pid")

    boot_head = str(boot_source.get("git_head") or "")
    current_head = str(source_snapshot.get("git_head") or "")
    if boot_head and current_head and boot_head != current_head:
        reasons.append("git_head_changed_since_boot")

    boot_digest = str(boot_source.get("tracked_worktree_digest") or "")
    current_digest = str(source_snapshot.get("tracked_worktree_digest") or "")
    if boot_digest != current_digest:
        reasons.append("tracked_worktree_changed_since_boot")

    stale = len(reasons) > 0
    if stale:
        if "serve_lock_points_to_other_pid" in reasons:
            alert_message = (
                "Not on the newest Thomas server process. " "Please restart Thomas so this tab uses the latest runtime."
            )
        else:
            alert_message = "Code changed after this Thomas server booted. " "Restart Thomas to run the newest version."
    else:
        alert_message = ""

    current = {
        "pid": os.getpid(),
        "source": source_snapshot,
        "lock": lock_snapshot,
    }
    status = {
        "checked_at_utc": _runtime_guard_iso_now(),
        "is_latest_code": not stale,
        "state": "ok" if not stale else "stale",
        "reasons": reasons,
        "alert_message": alert_message,
    }
    state["current"] = current
    state["status"] = status
    return status


async def _runtime_guard_loop(app: web.Application) -> None:
    """Background loop that periodically checks if code has changed."""
    while True:
        try:
            _runtime_guard_refresh(app)
        except asyncio.CancelledError:
            raise
        except (OSError, KeyError, ValueError) as exc:
            log.warning("Runtime guard check failed: %s", exc)
        state = _resolve_app_value(app, APP_RUNTIME_GUARD_STATE, expected_type=dict, default={})
        interval_s = float(state.get("check_interval_s") or 45.0)
        await asyncio.sleep(max(10.0, interval_s))
