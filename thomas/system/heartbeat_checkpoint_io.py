"""I/O helpers for ``heartbeat_checkpoint`` (git, workboard, state files).

Kept private to this package and used only by ``heartbeat_checkpoint``.
Split out so the orchestration module stays under the new-file growth cap.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

_SHORTSTAT_RE = re.compile(r"(?P<count>\d+)\s+(?:insertion|deletion)")

AGENT_ENV_KEYS: tuple[str, ...] = (
    "THOMAS_AGENT_ID",
    "AGENT_ID",
    "CODEX_AGENT_ID",
    "GEMINI_AGENT_ID",
    "CLAUDE_AGENT_ID",
)

CHECKPOINT_STATE_REL = Path("runtime") / "heartbeat_last_checkpoint.json"
DIRTY_RECORDS_REL = Path("runtime") / "heartbeat_dirty"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _git_status_paths(repo_root: Path) -> list[str]:
    """Return repo-relative paths with uncommitted changes."""
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=str(repo_root),
        capture_output=True,
        text=False,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git status failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return _parse_porcelain_z(proc.stdout)


def _parse_porcelain_z(blob: bytes) -> list[str]:
    if not blob:
        return []
    text = blob.decode("utf-8", "replace")
    paths: list[str] = []
    fields = text.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        if not entry:
            i += 1
            continue
        status = entry[:2]
        path = entry[3:] if len(entry) > 3 else ""
        if path:
            paths.append(path)
        # Renames consume the next field as the old path.
        if status[0] == "R" or status[1] == "R":
            i += 2
        else:
            i += 1
    return paths


def _safe_branch(repo_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, RuntimeError):
        # _safe_branch is invoked from the recovery path; never raise.
        return ""


def _shortstat_line_count(repo_root: Path, sha: str) -> int:
    """Added+removed line count for a commit via ``git show --shortstat``."""
    proc = subprocess.run(
        ["git", "show", "--shortstat", "--format=", sha],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return 0
    total = 0
    for match in _SHORTSTAT_RE.finditer(proc.stdout):
        total += int(match.group("count"))
    return total


def _git_head_sha(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _resolve_agent(explicit: str | None) -> str | None:
    if explicit and explicit.strip():
        return explicit.strip()
    for key in AGENT_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def _resolve_active_claim(repo_root: Path, agent: str) -> dict | None:
    """Return ``{'scope_paths': [...], 'task': '...'}`` for ``agent`` or None."""
    proc = subprocess.run(
        [sys.executable, "scripts/workboard_claim.py", "--list"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    target = agent.strip().lower()
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- agent="):
            continue
        fields = _parse_claim_line(stripped[len("- "):])
        if fields.get("agent", "").strip().lower() == target:
            scope_raw = fields.get("scope", "")
            scope_paths = [p.strip() for p in scope_raw.split(",") if p.strip()]
            return {"scope_paths": scope_paths, "task": fields.get("task", "")}
    return None


def _parse_claim_line(line: str) -> dict:
    fields: dict = {}
    for chunk in line.split(";"):
        if "=" in chunk:
            key, _, value = chunk.partition("=")
            fields[key.strip()] = value.strip()
    return fields


def _filter_paths_to_scope(dirty_paths: Iterable[str], scope_paths: Iterable[str]) -> list[str]:
    """Return dirty paths covered by any scope (file equality or dir prefix)."""
    scope_list = [s.replace("\\", "/").rstrip("/") for s in scope_paths if s]
    out: list[str] = []
    seen: set[str] = set()
    for raw in dirty_paths:
        norm = raw.replace("\\", "/")
        for s in scope_list:
            if norm == s or norm.startswith(s + "/"):
                if raw not in seen:
                    out.append(raw)
                    seen.add(raw)
                break
    return out


def _build_message(*, now: datetime, branch: str, paths: Sequence[str]) -> str:
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"heartbeat checkpoint: {ts}",
        "",
        "Auto-checkpoint by scripts/heartbeat.py --checkpoint.",
        f"Branch: {branch or '<detached>'}",
        f"Files: {len(paths)} (heartbeat-scoped)",
        "",
        "Thomas-Agent: heartbeat",
    ]
    return "\n".join(lines)


def _invoke_agent_commit(
    *,
    repo_root: Path,
    agent: str,
    include_paths: Sequence[str],
    message: str,
    dry_run: bool,
) -> dict:
    cmd: list[str] = [
        sys.executable,
        "scripts/agent_commit.py",
        "--message",
        message,
    ]
    if agent:
        cmd.extend(["--agent", agent])
    for path in include_paths:
        cmd.extend(["--include", path])
    if dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        return {
            "ok": False,
            "reason": _extract_failure_reason(output),
            "output": output,
        }
    sha = _git_head_sha(repo_root) if not dry_run else ""
    return {"ok": True, "sha": sha, "output": output}


def _extract_failure_reason(output: str) -> str:
    """Pick the most informative failure marker from agent_commit output."""
    lines = [line.strip() for line in output.splitlines()]
    for stripped in lines:
        if stripped.startswith("- failed gate:"):
            return stripped.split(":", 1)[1].strip()
    for stripped in lines:
        if stripped.startswith("- blocker_class:") or stripped.startswith("- message:"):
            return stripped.split(":", 1)[1].strip()[:120]
    for stripped in lines:
        if stripped.startswith("- "):
            return stripped[2:].strip()[:120]
    return "agent_commit_nonzero_exit"


def _last_checkpoint_state(repo_root: Path) -> dict | None:
    path = repo_root / CHECKPOINT_STATE_REL
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _save_last_checkpoint_state(
    repo_root: Path,
    *,
    now: datetime,
    sha: str,
    branch: str,
    status: str,
) -> None:
    path = repo_root / CHECKPOINT_STATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": now.isoformat(), "sha": sha, "branch": branch, "status": status}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _is_due(repo_root: Path, now: datetime, interval_minutes: int) -> bool:
    last = _last_checkpoint_state(repo_root)
    if not last or "ts" not in last:
        return True
    try:
        last_ts = datetime.fromisoformat(last["ts"])
    except (TypeError, ValueError):
        return True
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    return (now - last_ts).total_seconds() >= interval_minutes * 60


def _record_dirty(
    repo_root: Path,
    *,
    branch: str,
    dirty_paths: Sequence[str],
    reason: str,
    now: datetime,
    extras: dict | None = None,
) -> Path:
    records_dir = repo_root / DIRTY_RECORDS_REL
    records_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = now.strftime("%Y%m%dT%H%M%S")
    record_path = records_dir / f"{safe_ts}_{abs(hash(reason)) % 0xFFFF:04x}.json"
    payload = {
        "ts": now.isoformat(),
        "branch": branch,
        "dirty_file_count": len(dirty_paths),
        "dirty_paths": list(dirty_paths)[:200],
        "reason": reason,
    }
    if extras:
        payload["extras"] = extras
    record_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return record_path
