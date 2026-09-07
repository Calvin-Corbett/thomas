#!/usr/bin/env python3
"""Safe delegation/messaging wrappers for the workboard worker loop.

Split out of scripts/crew/workboard/worker.py (which had grown past the
monolith guard's unbaselined 800-line soft limit) so the split has a real
seam: everything here wraps a call into workboard_message / workboard_claim
/ workboard_task_manager / task_bot_runtime and converts it into a plain
(ok, error) or (ok, payload) tuple the worker loop can check without a
try/except of its own, with zero dependency back on worker.py's own
loop/CLI code. worker.py imports and re-exports every name defined here
under its original spot, so no external caller needed to change.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.tasks import manager as workboard_task_manager
    from scripts.crew.workboard import claim as workboard_claim
    from scripts.crew.workboard import message as workboard_message
    from thomas.core import task_bot_runtime
except ImportError:  # pragma: no cover
    from crew.tasks import manager as workboard_task_manager  # type: ignore
    from crew.workboard import claim as workboard_claim  # type: ignore
    from crew.workboard import message as workboard_message  # type: ignore

    from thomas.core import task_bot_runtime  # type: ignore

ROOT = Path(__file__).resolve().parents[3]


def _send_message_safe(
    *,
    workboard_path: Path,
    sender: str,
    recipient: str,
    task_id: str,
    summary: str,
    kind: str,
    priority: str,
    requested_action: str,
    decision: str,
) -> tuple[bool, str]:
    ok, payload = workboard_message.send_message(
        workboard_path,
        sender=sender,
        recipient=recipient,
        summary=summary,
        task_id=task_id,
        kind=kind,
        priority=priority,
        requested_action=requested_action,
        decision=decision,
    )
    if ok:
        return True, ""
    message = str(payload.get("error", "message send failed")) if isinstance(payload, dict) else str(payload)
    return False, message


def _release_claim_safe(
    *,
    workboard_path: Path,
    agent: str,
    allow_dirty_release: bool,
    dirty_release_reason: str,
    require_done_state: bool = False,
) -> tuple[bool, str]:
    ok, payload = workboard_claim.release(
        workboard_path,
        agent=agent,
        allow_dirty=bool(allow_dirty_release),
        dirty_reason=str(dirty_release_reason or ""),
        require_done_state=bool(require_done_state),
    )
    if ok:
        return True, ""
    return False, str(payload)


def _set_task_status_safe(
    *,
    workboard_path: Path,
    task_id: str,
    status: str,
    actor: str,
    enforce_transition: bool = True,
    evidence: str | None = None,
    evidence_not_before: datetime | None = None,
) -> tuple[bool, str]:
    ok, payload = workboard_task_manager.set_task_status(
        workboard_path, task_id=task_id, status=status, actor=actor, enforce_transition=bool(enforce_transition),
        evidence=evidence, evidence_not_before=evidence_not_before,
    )
    if ok:
        return True, ""
    message = str(payload.get("error", "task status update failed")) if isinstance(payload, dict) else str(payload)
    return False, message


def _git_head_sha(repo_root: Path) -> str | None:
    """Current HEAD sha, or None if unreadable; read before/after a pipeline run to detect a landed commit."""
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return str(proc.stdout or "").strip() or None


def _runtime_execution_id(task_id: str) -> str:
    try:
        payload = task_bot_runtime.find_by_task_id(task_id, repo_root=ROOT)
    except (OSError, ValueError, RuntimeError, KeyError, AttributeError):
        return ""
    return str((payload or {}).get("execution_id") or "").strip()


def _request_immediate_dispatch(
    *,
    workboard_path: Path,
    agent: str,
    task_manager_agent: str,
    task_id: str,
    dispatch_lookback_minutes: float,
) -> tuple[bool, dict[str, object]]:
    _send_message_safe(
        workboard_path=workboard_path,
        sender=agent,
        recipient=task_manager_agent,
        task_id=task_id,
        summary=f"request immediate redispatch after completing `{task_id}`",
        kind="coordination",
        priority="p1",
        requested_action="assign next available task",
        decision="pending",
    )
    ok_dispatch, payload_dispatch = workboard_task_manager.dispatch_idle_agents_once(
        workboard_path=workboard_path,
        task_manager_agent=task_manager_agent,
        max_dispatch_per_cycle=1,
        online_lookback_minutes=max(1.0, float(dispatch_lookback_minutes)),
        apply=True,
    )
    if not ok_dispatch:
        return False, payload_dispatch
    return True, payload_dispatch


def _finalize_landed_done(
    *,
    workboard_path: Path,
    task_id: str,
    agent: str,
    task_manager_agent: str,
    landed_sha: str,
    evidence_not_before: datetime,
    runtime_execution_id: str,
    repo_root: Path,
    elapsed_total: float,
    run_count: int,
    log_path: str,
    auto_release_success: bool,
    allow_dirty_release: bool,
    dirty_release_reason: str,
    request_dispatch_on_complete: bool,
    dispatch_lookback_minutes: float,
) -> dict[str, object]:
    """Attempt the `done` transition for a pipeline run that landed a commit,
    then either report success or -- if the transition itself was REFUSED
    (e.g. the landed commit failed evidence verification) -- report a
    refusal (review-round fix, coordinator-reviewed).

    Before this fix, worker.py's caller unconditionally sent the
    "completed"/approved message, called `task_bot_runtime.complete_execution`,
    and (with `--auto-release-success`) released the claim even when the
    `done` transition itself was refused -- and the loop's `completion_count`
    was already credited before this outcome was known. With
    `--no-auto-release-success` specifically, nothing else touched
    `failure_count`/`held_count`/`inbox_blocked_count`, so the loop's overall
    `ok` could read `True` with a refused done hidden inside it.

    Returns a plain dict the caller folds into its own loop-local counters
    (never mutates caller state directly, so this stays testable in
    isolation): `refused` (bool -- a commit DID land, unlike the held case,
    but the done transition itself was refused), `error` (str | None),
    `failure` (bool -- a post-done step, claim release or immediate
    redispatch, failed), `dispatch_requested` (bool), `dispatch_assigned`
    (int).
    """
    ok_done, err_done = _set_task_status_safe(
        workboard_path=workboard_path,
        task_id=task_id,
        status="done",
        actor=agent,
        enforce_transition=True,
        evidence=f"commit:{landed_sha}",
        evidence_not_before=evidence_not_before,
    )
    if not ok_done:
        _send_message_safe(
            workboard_path=workboard_path,
            sender=agent,
            recipient=task_manager_agent,
            task_id=task_id,
            summary=(
                f"done refused for `{task_id}`: {err_done or 'evidence verification failed'} - "
                "task remains in review"
            ),
            kind="blocker",
            priority="p1",
            decision="pending",
            requested_action="review the evidence verification failure and re-land or fix",
        )
        return {"refused": True, "error": err_done, "failure": False, "dispatch_requested": False, "dispatch_assigned": 0}

    if runtime_execution_id:
        try:
            task_bot_runtime.complete_execution(
                runtime_execution_id,
                actor=agent,
                repo_root=repo_root,
                summary=f"Worker completed `{task_id}` in {elapsed_total:.2f}s.",
            )
        except (OSError, ValueError, RuntimeError, KeyError, AttributeError):
            pass
    _send_message_safe(
        workboard_path=workboard_path,
        sender=agent,
        recipient=task_manager_agent,
        task_id=task_id,
        summary=f"completed `{task_id}` using {run_count} command(s) in {elapsed_total:.2f}s (log: {log_path})",
        kind="status",
        priority="p1",
        requested_action="none",
        decision="approved",
    )
    result: dict[str, object] = {
        "refused": False,
        "error": None,
        "failure": False,
        "dispatch_requested": False,
        "dispatch_assigned": 0,
    }
    if not auto_release_success:
        return result

    ok_release, err_release = _release_claim_safe(
        workboard_path=workboard_path,
        agent=agent,
        allow_dirty_release=allow_dirty_release,
        dirty_release_reason=dirty_release_reason,
        require_done_state=True,
    )
    if not ok_release:
        result["failure"] = True
        result["error"] = err_release
        _send_message_safe(
            workboard_path=workboard_path,
            sender=agent,
            recipient=task_manager_agent,
            task_id=task_id,
            summary=f"completed `{task_id}` but failed to release claim",
            kind="blocker",
            priority="p0",
            requested_action="release claim manually",
            decision="pending",
        )
        return result

    if request_dispatch_on_complete:
        result["dispatch_requested"] = True
        ok_dispatch, payload_dispatch = _request_immediate_dispatch(
            workboard_path=workboard_path,
            agent=agent,
            task_manager_agent=task_manager_agent,
            task_id=task_id,
            dispatch_lookback_minutes=dispatch_lookback_minutes,
        )
        if ok_dispatch:
            result["dispatch_assigned"] = int(payload_dispatch.get("assigned_count", 0) or 0)
        else:
            result["failure"] = True
            result["error"] = str(payload_dispatch.get("error", "immediate dispatch request failed"))
            _send_message_safe(
                workboard_path=workboard_path,
                sender=agent,
                recipient=task_manager_agent,
                task_id=task_id,
                summary="immediate redispatch request failed",
                kind="coordination",
                priority="p1",
                decision="pending",
                requested_action="run task manager monitor/dispatch cycle",
            )
    return result


def _inbox_interrupt(
    *,
    workboard_path: Path,
    agent: str,
) -> tuple[bool, dict[str, object]]:
    ok, payload = workboard_message.unread_messages(workboard_path, agent=agent)
    if not ok:
        return False, {
            "error": str(payload.get("error") or "failed to read worker inbox"),
            "unread_count": 0,
            "messages": [],
        }
    messages = [dict(row) for row in list(payload.get("messages") or []) if isinstance(row, dict)]
    return True, {
        "unread_count": len(messages),
        "messages": messages,
        "msg_ids": [str(row.get("msg_id") or "") for row in messages if str(row.get("msg_id") or "").strip()],
    }
