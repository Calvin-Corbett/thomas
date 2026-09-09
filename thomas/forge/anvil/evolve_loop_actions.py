"""Out-of-band actions for the evolve loop: approve / reject / pause.

Also owns the collaborator-binding helper that defaults the planner, session
runner, and promoter to the real green-mirror engine (imported lazily so unit
tests that inject fakes never pull in the heavy engine).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .evolve_loop_state import (
    STATUS_PAUSED,
    STATUS_RUNNING,
    EvolveLoopState,
    append_event,
    load_loop_state,
    now_iso,
    save_loop_state,
    write_control,
)
from .evolve_planner import EvolveBacklog, EvolveGoal, plan_backlog

# Collaborator types (injected for testing; defaulted to the real engine).
PlannerFn = Callable[..., EvolveBacklog]
SessionRunnerFn = Callable[..., dict[str, Any]]
PromoterFn = Callable[..., dict[str, Any]]


def bind_real_collaborators(
    planner: PlannerFn | None,
    session_runner: SessionRunnerFn | None,
    promoter: PromoterFn | None,
    *,
    mode: str = "classic",
) -> tuple[PlannerFn, SessionRunnerFn, PromoterFn]:
    """Default the injected collaborators to the real green-mirror engine.

    ``mode`` selects the per-goal creative engine when ``session_runner`` is not
    injected: ``"classic"`` (the single-pass green-mirror engine) or ``"funnel"``
    (the additive multi-agent funnel, which itself wraps the classic engine as its
    builder and never touches the blue-owned promotion gate). An explicitly
    injected ``session_runner`` always wins over ``mode`` so tests stay in control.

    Imported lazily so unit tests (which inject fakes) never pull in the heavy
    engine module or its subprocess machinery.
    """
    if planner is None:
        planner = plan_backlog
    if session_runner is None:
        if str(mode).strip().lower() == "funnel":
            from .evolve_funnel import run_funnel_session

            session_runner = run_funnel_session
        else:
            from .evolve import run_evolve_session

            session_runner = run_evolve_session
    if promoter is None:
        from .evolve import promote_evolve_session

        promoter = promote_evolve_session
    return planner, session_runner, promoter


def resolve_default_root() -> Path:
    # Imported lazily to keep this module importable without the engine present.
    from .evolve import resolve_repo_root

    return resolve_repo_root()


def _find_pending(state: EvolveLoopState, approval_id: str) -> dict[str, Any] | None:
    for item in state.pending_approvals:
        if str(item.get("id")) == str(approval_id):
            return item
    return None


def approve_pending(
    project_root: Path | None,
    approval_id: str,
    *,
    profile: str = "",
    timeout_seconds: int = 1800,
    session_runner: SessionRunnerFn | None = None,
    promoter: PromoterFn | None = None,
) -> dict[str, Any]:
    """Approve a held change: re-derive its goal in the mirror and promote it.

    Re-running (rather than promoting a now-stale mirror) is what makes deferred
    approval correct -- the goal is the durable unit. If the change no longer
    reproduces and verifies, the approval is marked ``failed`` honestly.
    """
    root = Path(project_root) if project_root is not None else resolve_default_root()
    _planner, session_runner, promoter = bind_real_collaborators(None, session_runner, promoter)
    state = load_loop_state(root)
    pending = _find_pending(state, approval_id)
    if pending is None:
        raise RuntimeError(f"pending approval '{approval_id}' not found")
    if pending.get("status") != "pending":
        return {"ok": True, "already": pending.get("status"), "approval": pending}

    goal = EvolveGoal.from_dict(dict(pending.get("goal") or {}))
    result = session_runner(
        root,
        goal=goal.goal_prompt,
        profile=profile,
        passes=1,
        promote_on_pass=False,
        refactor_first=(goal.category == "refactor"),
        timeout_seconds=timeout_seconds,
    )
    session = dict(result.get("session") or {})
    if not bool(session.get("promotable")):
        pending["status"] = "failed"
        pending["reason"] = f"re-run not promotable: {session.get('status')}"
        save_loop_state(root, state)
        return {"ok": False, "approval": pending, "session": session}

    promoter(root, session_id=str(session.get("session_id") or ""))
    pending["status"] = "approved"
    pending["approved_at"] = now_iso()
    pending["promoted_session_id"] = str(session.get("session_id") or "")
    state.counters["promoted"] = int(state.counters.get("promoted", 0)) + 1
    save_loop_state(root, state)
    append_event(root, {"type": "approval_promoted", "approval_id": approval_id, "goal_id": goal.id}, None)
    return {"ok": True, "approval": pending, "session": session}


def reject_pending(project_root: Path | None, approval_id: str, *, reason: str = "") -> dict[str, Any]:
    """Dismiss a held change without promoting it."""
    root = Path(project_root) if project_root is not None else resolve_default_root()
    state = load_loop_state(root)
    pending = _find_pending(state, approval_id)
    if pending is None:
        raise RuntimeError(f"pending approval '{approval_id}' not found")
    pending["status"] = "rejected"
    pending["reason"] = reason or "rejected by user"
    pending["rejected_at"] = now_iso()
    save_loop_state(root, state)
    append_event(root, {"type": "approval_rejected", "approval_id": approval_id}, None)
    return {"ok": True, "approval": pending}


def request_pause(project_root: Path | None) -> dict[str, Any]:
    """Ask a running loop to stop after its current iteration (cross-process)."""
    root = Path(project_root) if project_root is not None else resolve_default_root()
    write_control(root, stop=True)
    state = load_loop_state(root)
    if state.status == STATUS_RUNNING:
        state.status = STATUS_PAUSED
        save_loop_state(root, state)
    return state.to_dict()
