"""Crew.Brief Layer 1 — periodic auto-checkpoint of dirty worktrees.

When a heartbeat tick fires, this module checks the worktree for
uncommitted changes inside the active agent's workboard claim and runs
``scripts/agent_commit.py`` to produce a tagged checkpoint commit.

Failures are logged and recorded under ``runtime/heartbeat_dirty/`` but
never raised, so the heartbeat loop above us keeps ticking. Configuration
goes via env vars (``thomas.toml`` is in the protected list); see
``DEFAULT_INTERVAL_MINUTES``, ``INTERVAL_ENV``, ``DISABLE_ENV``,
``FORCE_ENV`` for the surface.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from thomas.system.heartbeat_checkpoint_io import (
    _build_message,
    _filter_paths_to_scope,
    _git_status_paths,
    _invoke_agent_commit,
    _is_due,
    _record_dirty,
    _resolve_active_claim,
    _resolve_agent,
    _safe_branch,
    _save_last_checkpoint_state,
    _shortstat_line_count,
    _truthy,
)

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_MINUTES = 5
INTERVAL_ENV = "THOMAS_HEARTBEAT_CHECKPOINT_INTERVAL_MINUTES"
DISABLE_ENV = "THOMAS_HEARTBEAT_DISABLE_CHECKPOINT"
FORCE_ENV = "THOMAS_HEARTBEAT_FORCE_CHECKPOINT"


@dataclass(frozen=True)
class CheckpointResult:
    """Outcome of a single heartbeat checkpoint attempt."""

    status: str  # "clean" | "committed" | "recorded" | "skipped" | "disabled"
    message: str
    branch: str = ""
    dirty_file_count: int = 0
    commit_sha: str = ""
    record_path: str = ""
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def run_checkpoint(
    *,
    agent: str | None = None,
    repo_root: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CheckpointResult:
    """Run one checkpoint tick. Never raises -- catches and degrades."""
    try:
        return _run_checkpoint_inner(
            agent=agent,
            repo_root=repo_root,
            force=force,
            dry_run=dry_run,
            now=now or datetime.now(timezone.utc),
        )
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
        logger.exception("heartbeat checkpoint: unexpected failure")
        root = repo_root or _default_repo_root()
        try:
            record = _record_dirty(
                root,
                branch=_safe_branch(root),
                dirty_paths=[],
                reason=f"unexpected_error:{type(exc).__name__}: {exc}",
                now=datetime.now(timezone.utc),
            )
            return CheckpointResult(
                status="recorded",
                message=f"unexpected error: {exc}",
                record_path=str(record),
            )
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            # Recovery path itself failed -- still must not raise.
            return CheckpointResult(status="recorded", message=f"unexpected error: {exc}")


def _run_checkpoint_inner(
    *,
    agent: str | None,
    repo_root: Path | None,
    force: bool,
    dry_run: bool,
    now: datetime,
) -> CheckpointResult:
    if _truthy(os.environ.get(DISABLE_ENV)):
        return CheckpointResult(status="disabled", message="checkpoint disabled via env")

    root = repo_root or _default_repo_root()
    interval = _interval_minutes()
    force = force or _truthy(os.environ.get(FORCE_ENV))

    if not force and not _is_due(root, now, interval):
        return CheckpointResult(
            status="skipped",
            message=f"throttled (< {interval}m since last checkpoint)",
        )

    branch = _safe_branch(root)
    dirty_paths = _git_status_paths(root)
    if not dirty_paths:
        logger.debug("heartbeat: worktree clean")
        _save_last_checkpoint_state(root, now=now, sha="", branch=branch, status="clean")
        return CheckpointResult(status="clean", message="worktree clean", branch=branch)

    resolved_agent = _resolve_agent(agent)
    claim = _resolve_active_claim(root, resolved_agent) if resolved_agent else None
    if claim is None:
        return _record_and_result(
            root,
            now=now,
            branch=branch,
            dirty_paths=dirty_paths,
            reason="no_active_claim",
            user_message="no active workboard claim for current agent",
            log_msg="heartbeat: dirty worktree but no active claim for agent=%s; recorded to %s",
            log_args=(resolved_agent or "<unset>",),
        )

    in_scope = _filter_paths_to_scope(dirty_paths, claim["scope_paths"])
    if not in_scope:
        return _record_and_result(
            root,
            now=now,
            branch=branch,
            dirty_paths=dirty_paths,
            reason="dirty_outside_claim_scope",
            user_message="dirty paths fall outside active claim scope",
            log_msg="heartbeat: %d dirty paths but none inside claim scope; recorded to %s",
            log_args=(len(dirty_paths),),
        )

    message = _build_message(now=now, branch=branch, paths=in_scope)
    commit = _invoke_agent_commit(
        repo_root=root,
        agent=resolved_agent or "",
        include_paths=in_scope,
        message=message,
        dry_run=dry_run,
    )

    if not commit.get("ok"):
        reason_short = commit.get("reason", "unknown")
        return _record_and_result(
            root,
            now=now,
            branch=branch,
            dirty_paths=dirty_paths,
            reason=f"agent_commit_failed:{reason_short}",
            user_message=f"agent_commit failed: {reason_short}",
            log_msg="heartbeat: agent_commit failed (%s); recorded to %s",
            log_args=(reason_short,),
            extras={"agent_commit_output": commit.get("output", "")[:4000]},
        )

    sha = commit.get("sha", "")
    line_count = _shortstat_line_count(root, sha) if sha else 0
    _save_last_checkpoint_state(root, now=now, sha=sha, branch=branch, status="committed")
    logger.info(
        "heartbeat: committed checkpoint %s on %s (%d files, %d lines changed)",
        sha[:12] or "<unknown>",
        branch,
        len(in_scope),
        line_count,
    )
    return CheckpointResult(
        status="committed",
        message=f"checkpointed {len(in_scope)} files",
        branch=branch,
        dirty_file_count=len(in_scope),
        commit_sha=sha,
        extras={"line_count": line_count},
    )


def _record_and_result(
    root: Path,
    *,
    now: datetime,
    branch: str,
    dirty_paths: Sequence[str],
    reason: str,
    user_message: str,
    log_msg: str,
    log_args: tuple,
    extras: dict | None = None,
) -> CheckpointResult:
    record = _record_dirty(
        root,
        branch=branch,
        dirty_paths=dirty_paths,
        reason=reason,
        now=now,
        extras=extras,
    )
    logger.warning(log_msg, *log_args, record)
    return CheckpointResult(
        status="recorded",
        message=user_message,
        branch=branch,
        dirty_file_count=len(dirty_paths),
        record_path=str(record),
    )


def _interval_minutes() -> int:
    raw = os.environ.get(INTERVAL_ENV, "").strip()
    if not raw:
        return DEFAULT_INTERVAL_MINUTES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_INTERVAL_MINUTES


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
