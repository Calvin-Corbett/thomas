"""Crew.Brief Layer 3 — periodic dirty-state monitor.

Runs inside ``thomas.tray_agent`` (the always-on Windows tray process). When
no Thomas agent session is detected to be active, this module periodically
scans all known git worktrees for orphaned dirty state and emits a tray
notification recommending a manual checkpoint.

Coverage targets the "laptop sat closed all weekend, tray boots up Monday
morning, noticed stale dirty work" pattern that L1 (heartbeat per-tick
checkpoint) and L2 (startup-time orphan detection in ``startup_router.py``)
don't cover by themselves: L1 needs an active heartbeat loop, L2 needs a
new agent session to actually start.

Public API:

- :func:`is_agent_session_active(repo_root)` — heuristic check for any
  active agent process. True if any agent appears to be alive.
- :func:`scan_worktrees_for_dirty(repo_root)` — list each worktree with
  its dirty-file count and active claim, if any.
- :func:`should_notify(scan, last_notify_ts)` — debounce gate.
- :func:`build_notification_payload(scan)` — text body for a tray toast.

Wiring (deferred to a follow-up patch that touches ``agent.py`` directly):
schedule ``scan_worktrees_for_dirty`` from the tray's existing health-check
thread loop. When ``is_agent_session_active(...)`` returns False AND
``scan`` returns dirty worktrees, call ``build_notification_payload(scan)``
and surface via the tray's existing notification path.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_SESSION_QUIET_MINUTES = 30.0
DEFAULT_NOTIFY_COOLDOWN_MINUTES = 60.0
DEFAULT_HEARTBEAT_DIRTY_LOOKBACK_HOURS = 168.0  # one week


@dataclass
class WorktreeStatus:
    path: str
    branch: str
    dirty_file_count: int = 0
    dirty_paths: list[str] = field(default_factory=list)
    active_claim: dict[str, str] | None = None


@dataclass
class ScanResult:
    repo_root: str
    worktrees: list[WorktreeStatus] = field(default_factory=list)
    heartbeat_dirty_records: int = 0
    scanned_at: str = ""

    @property
    def dirty_worktree_count(self) -> int:
        return sum(1 for w in self.worktrees if w.dirty_file_count > 0)


def _run_git(args: Sequence[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if proc.returncode != 0:
            return ""
        return proc.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _list_worktrees(repo_root: Path) -> list[tuple[str, str]]:
    """Return [(worktree_path, branch_name), ...] for the repo's worktrees."""
    raw = _run_git(["worktree", "list", "--porcelain"], repo_root)
    entries: list[tuple[str, str]] = []
    current_path = ""
    current_branch = ""
    for line in raw.splitlines():
        if line.startswith("worktree "):
            if current_path:
                entries.append((current_path, current_branch))
            current_path = line[len("worktree ") :].strip()
            current_branch = ""
        elif line.startswith("branch "):
            ref = line[len("branch ") :].strip()
            if ref.startswith("refs/heads/"):
                current_branch = ref[len("refs/heads/") :]
            else:
                current_branch = ref
        elif line.startswith("detached"):
            current_branch = "(detached)"
    if current_path:
        entries.append((current_path, current_branch))
    return entries


def _worktree_dirty_paths(worktree_path: str) -> list[str]:
    raw = _run_git(["status", "--porcelain"], Path(worktree_path))
    paths: list[str] = []
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if path:
            paths.append(path)
    return paths


_CLAIM_HEADING_RE = re.compile(r"^##\s+agent claims\s*$", re.IGNORECASE)
_NEXT_SECTION_RE = re.compile(r"^##\s+", re.IGNORECASE)


def _parse_active_claim_for_branch(workboard_path: Path, branch: str) -> dict[str, str] | None:
    if not workboard_path.exists() or not branch:
        return None
    try:
        lines = workboard_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    in_claims = False
    for line in lines:
        if _CLAIM_HEADING_RE.match(line):
            in_claims = True
            continue
        if in_claims and _NEXT_SECTION_RE.match(line):
            break
        if not in_claims:
            continue
        stripped = line.strip()
        if not stripped.startswith("- ") or stripped.lower() in {"- none", "- (none)"}:
            continue
        fields: dict[str, str] = {}
        for chunk in [piece.strip() for piece in stripped[2:].split(";") if piece.strip()]:
            if "=" not in chunk:
                continue
            key, _, value = chunk.partition("=")
            fields[key.strip().lower()] = value.strip()
        agent = fields.get("agent", "")
        if agent and (agent == branch or branch.endswith(agent) or agent in branch):
            return fields
    return None


def _count_recent_heartbeat_dirty(repo_root: Path, lookback_hours: float) -> int:
    dirty_dir = repo_root / "runtime" / "heartbeat_dirty"
    if not dirty_dir.exists():
        return 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=float(lookback_hours))
    except (TypeError, ValueError):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_HEARTBEAT_DIRTY_LOOKBACK_HOURS)
    count = 0
    for record in sorted(dirty_dir.glob("*.json"), reverse=True)[:50]:
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        ts_raw = str(data.get("ts") or "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts >= cutoff:
            count += 1
    return count


def is_agent_session_active(repo_root: Path, quiet_minutes: float = DEFAULT_SESSION_QUIET_MINUTES) -> bool:
    """True if an agent session looks alive (recent heartbeat-tick activity).

    The signal is "did anything write to runtime/heartbeat_dirty/ OR run a
    successful agent_commit within `quiet_minutes`?" If no, treat the
    environment as idle and safe to surface orphan warnings without
    competing with an active session.
    """
    try:
        threshold = datetime.now(timezone.utc) - timedelta(minutes=float(quiet_minutes))
    except (TypeError, ValueError):
        threshold = datetime.now(timezone.utc) - timedelta(minutes=DEFAULT_SESSION_QUIET_MINUTES)

    heartbeat_dirty_dir = repo_root / "runtime" / "heartbeat_dirty"
    if heartbeat_dirty_dir.exists():
        for record in sorted(heartbeat_dirty_dir.glob("*.json"), reverse=True)[:10]:
            try:
                stat = record.stat()
            except OSError:
                continue
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if mtime >= threshold:
                return True

    # Fall back to git reflog: any commit in the last quiet_minutes is "alive".
    raw = _run_git(["reflog", "--date=iso-strict", "-n", "5"], repo_root)
    for line in raw.splitlines():
        match = re.search(r"@\{(?P<ts>[^}]+)\}", line)
        if not match:
            continue
        try:
            ts = datetime.fromisoformat(match.group("ts"))
        except ValueError:
            continue
        if ts >= threshold:
            return True
    return False


def scan_worktrees_for_dirty(repo_root: Path) -> ScanResult:
    """Walk every worktree, report dirty file count and active claim."""
    workboard_path = repo_root / "plans" / "thomas" / "WORKBOARD.md"
    result = ScanResult(
        repo_root=str(repo_root),
        scanned_at=datetime.now(timezone.utc).isoformat(),
        heartbeat_dirty_records=_count_recent_heartbeat_dirty(repo_root, DEFAULT_HEARTBEAT_DIRTY_LOOKBACK_HOURS),
    )
    for path, branch in _list_worktrees(repo_root):
        dirty_paths = _worktree_dirty_paths(path)
        active_claim = _parse_active_claim_for_branch(workboard_path, branch) if branch else None
        result.worktrees.append(
            WorktreeStatus(
                path=path,
                branch=branch,
                dirty_file_count=len(dirty_paths),
                dirty_paths=dirty_paths[:10],
                active_claim=active_claim,
            )
        )
    return result


def should_notify(
    scan: ScanResult, last_notify_ts: datetime | None, cooldown_minutes: float = DEFAULT_NOTIFY_COOLDOWN_MINUTES
) -> bool:
    if scan.dirty_worktree_count == 0:
        return False
    if last_notify_ts is None:
        return True
    try:
        elapsed = datetime.now(timezone.utc) - last_notify_ts
    except TypeError:
        return True
    return elapsed >= timedelta(minutes=float(cooldown_minutes))


def build_notification_payload(scan: ScanResult) -> dict[str, str]:
    """Tray-friendly notification body."""
    dirty_count = scan.dirty_worktree_count
    if dirty_count == 0:
        return {"title": "", "body": "", "level": "info"}
    if dirty_count == 1:
        target = next(w for w in scan.worktrees if w.dirty_file_count > 0)
        body = (
            f"Worktree at {target.path} (branch {target.branch}) has "
            f"{target.dirty_file_count} dirty file(s) and no recent agent activity. "
            f"Consider running `python scripts/heartbeat.py --checkpoint --force` "
            f"to checkpoint before the next session."
        )
    else:
        body = (
            f"{dirty_count} worktrees have dirty state and no active agent session. "
            f"Run `python scripts/heartbeat.py --checkpoint --force` from each "
            f"to checkpoint before the next session."
        )
    return {
        "title": "Thomas: orphaned dirty state detected",
        "body": body,
        "level": "warn",
    }
