"""Evolve loop -- the self-recursive runner that makes Thomas improve itself.

The loop ties the pieces together into a continuous cycle:

    plan  ->  pick highest-leverage goal  ->  run it in the green mirror
          ->  let the autonomy gate decide  ->  promote / hold / reject
          ->  record  ->  re-plan  ->  repeat   (until budget or backlog runs dry)

It is budget-bounded (max iterations / promotions / wall-clock) and persists its
full state + an event stream under ``.thomas/evolve/loop/`` so a dashboard or
chat surface can watch it live and a human can approve held changes out-of-band.

Promotion timing is deliberate: the green mirror is a single slot reset each
session, so a verified change promotes immediately; a held change re-derives on
approval. State lives in ``evolve_loop_state``; actions in ``evolve_loop_actions``.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evolve_supervisor import (
    ACTION_APPROVE,
    ACTION_PROMOTE,
    DEFAULT_POSTURE,
    EvolvePosture,
    build_session_verifier,
    decide_for_session,
    evaluate_spend_governor,
    parse_posture,
)

from .evolve_loop_actions import (
    PlannerFn,
    PromoterFn,
    SessionRunnerFn,
    approve_pending,
    bind_real_collaborators,
    reject_pending,
    request_pause,
    resolve_default_root,
)
from .evolve_loop_learning import rerank_by_history
from .evolve_loop_state import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_PAUSED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    EventSink,
    EvolveLoopState,
    LoopBudget,
    append_event,
    clear_control,
    history_item,
    load_loop_state,
    loop_root,
    make_pending_approval,
    now_iso,
    read_control,
    save_loop_state,
)
from .evolve_planner import CATEGORIES, EvolveGoal

logger = logging.getLogger(__name__)

__all__ = [
    "STATUS_IDLE",
    "STATUS_RUNNING",
    "STATUS_PAUSED",
    "STATUS_DONE",
    "STATUS_STOPPED",
    "STATUS_ERROR",
    "LoopBudget",
    "EvolveLoopState",
    "loop_root",
    "load_loop_state",
    "save_loop_state",
    "read_control",
    "run_evolve_loop",
    "approve_pending",
    "reject_pending",
    "request_pause",
]


def _session_spend_watchdog_verdicts(session: dict[str, Any]) -> list[dict[str, Any]]:
    verdicts: list[dict[str, Any]] = []

    def collect(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for item in rows:
            if not isinstance(item, dict) or not bool(item.get("spend_watchdog_triggered")):
                continue
            verdict = item.get("spend_watchdog_verdict")
            if isinstance(verdict, dict):
                verdicts.append(dict(verdict))
            else:
                verdicts.append({"message": str(item.get("stderr_tail") or "spend watchdog terminated session")})

    collect(session.get("pass_results"))
    refactor_results = session.get("refactor_results")
    if isinstance(refactor_results, dict):
        collect(refactor_results.get("pass_results"))
        collect(refactor_results.get("health_reviews"))
    for key in ("spend_governor_checks", "spend_ledger_writes"):
        rows = session.get(key)
        if not isinstance(rows, list):
            continue
        for item in rows:
            if isinstance(item, dict) and item.get("enabled") and not item.get("ok", True):
                verdicts.append(dict(item))
    rejections = session.get("spend_governor_rejections")
    if isinstance(rejections, list):
        for item in rejections:
            verdicts.append({"code": "session_spend_governor_rejection", "message": str(item)})
    return verdicts


def run_evolve_loop(
    project_root: Path | None = None,
    *,
    posture: str | EvolvePosture = DEFAULT_POSTURE,
    focus: str = "",
    categories: list[str] | None = None,
    max_iterations: int = 6,
    max_promotions: int = 4,
    max_wall_seconds: float = 0.0,
    timeout_seconds: int = 1800,
    profile: str = "",
    mode: str = "classic",
    planner: PlannerFn | None = None,
    session_runner: SessionRunnerFn | None = None,
    promoter: PromoterFn | None = None,
    now_fn: Callable[[], float] | None = None,
    stop_check: Callable[[], bool] | None = None,
    event_sink: EventSink | None = None,
    reset: bool = True,
) -> dict[str, Any]:
    """Run the self-recursive evolve loop until budget or backlog is exhausted.

    Returns the final loop-state dict. Heavy collaborators default to the real
    green-mirror engine; pass fakes to unit test the control flow.
    """
    root = Path(project_root) if project_root is not None else resolve_default_root()
    posture_enum = parse_posture(posture)
    now = now_fn or time.monotonic
    planner, session_runner, promoter = bind_real_collaborators(planner, session_runner, promoter, mode=mode)

    state = EvolveLoopState() if reset else load_loop_state(root)
    state.status = STATUS_RUNNING
    state.posture = posture_enum.value
    state.focus = focus
    state.categories = list(categories) if categories else list(CATEGORIES)
    state.budget = LoopBudget(
        max_iterations=int(max_iterations),
        max_promotions=int(max_promotions),
        max_wall_seconds=float(max_wall_seconds),
    )
    state.started_at = state.started_at or now_iso()
    state.finished_at = ""
    state.last_error = ""
    state.run_id = uuid.uuid4().hex[:12]
    save_loop_state(root, state)
    clear_control(root)
    append_event(root, {"type": "loop_start", "posture": state.posture, "focus": focus, "mode": mode}, event_sink)

    # Default stop check honours a cross-process pause flag (control.json) so the
    # dashboard can ask a subprocess-launched loop to stop between iterations.
    _stop_check = stop_check or (lambda: bool(read_control(root).get("stop")))
    attempted_ids: set[str] = set()
    start_clock = now()

    def _budget_exhausted() -> tuple[bool, str]:
        if state.budget.max_iterations and state.iteration >= state.budget.max_iterations:
            return True, "max_iterations reached"
        if state.budget.max_promotions and state.counters["promoted"] >= state.budget.max_promotions:
            return True, "max_promotions reached"
        if state.budget.max_wall_seconds and (now() - start_clock) >= state.budget.max_wall_seconds:
            return True, "wall-clock budget reached"
        return False, ""

    stop_reason = ""
    try:
        while True:
            if _stop_check():
                state.status = STATUS_STOPPED
                stop_reason = "stop requested"
                break

            spend_verdict = evaluate_spend_governor(root)
            if not spend_verdict.ok:
                state.status = STATUS_STOPPED
                state.last_error = spend_verdict.message
                stop_reason = f"spend governor: {spend_verdict.message}"
                append_event(root, {"type": "spend_governor_stop", "verdict": spend_verdict.to_dict()}, event_sink)
                break

            exhausted, why = _budget_exhausted()
            if exhausted:
                stop_reason = why
                break

            # (Re)plan when the backlog is empty.
            if not state.backlog:
                backlog = planner(root, focus=focus, categories=set(state.categories) or None)
                state.signals = dict(backlog.signals)
                fresh = [g for g in backlog.goals if g.id not in attempted_ids]
                kept, dropped = rerank_by_history(fresh, state.history)
                if dropped:
                    state.counters["skipped_tarpit"] = state.counters.get("skipped_tarpit", 0) + len(dropped)
                    attempted_ids.update(g.id for g in dropped)
                    append_event(
                        root,
                        {"type": "tarpits_skipped", "count": len(dropped), "goal_ids": [g.id for g in dropped]},
                        event_sink,
                    )
                state.counters["planned"] += len(kept)
                state.backlog = [g.to_dict() for g in kept]
                save_loop_state(root, state)
                append_event(root, {"type": "planned", "count": len(kept), "signals": state.signals}, event_sink)
                if not state.backlog:
                    stop_reason = "backlog empty -- nothing left to improve"
                    break

            goal = EvolveGoal.from_dict(state.backlog.pop(0))
            attempted_ids.add(goal.id)
            state.iteration += 1
            state.current = goal.to_dict()
            save_loop_state(root, state)
            append_event(
                root,
                {
                    "type": "goal_start",
                    "iteration": state.iteration,
                    "goal_id": goal.id,
                    "title": goal.title,
                    "category": goal.category,
                    "risk_tier": goal.risk_tier,
                },
                event_sink,
            )

            # ---- run the goal in the green mirror (heavy / injected) ----
            try:
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
                session.setdefault("category", goal.category)
                session.setdefault("risk_tier", goal.risk_tier)
                spend_watchdog_verdicts = _session_spend_watchdog_verdicts(session)
            except Exception as exc:  # noqa: BLE001 - one bad session must not kill the loop
                logger.warning("evolve loop session failed for %s: %s", goal.id, exc)
                state.counters["failed"] += 1
                state.history.append(
                    {
                        "iteration": state.iteration,
                        "goal_id": goal.id,
                        "title": goal.title,
                        "category": goal.category,
                        "risk_tier": goal.risk_tier,
                        "decision": {"action": "reject", "reason": f"session error: {exc}"},
                        "promoted": False,
                        "at": now_iso(),
                    }
                )
                state.current = None
                save_loop_state(root, state)
                append_event(root, {"type": "goal_error", "goal_id": goal.id, "error": str(exc)}, event_sink)
                continue

            if spend_watchdog_verdicts:
                first_verdict = spend_watchdog_verdicts[0]
                state.last_error = str(first_verdict.get("message") or "spend watchdog terminated session")
                append_event(
                    root,
                    {
                        "type": "spend_watchdog_stop",
                        "iteration": state.iteration,
                        "goal_id": goal.id,
                        "verdicts": spend_watchdog_verdicts,
                    },
                    event_sink,
                )

            # ---- gate decides promote / hold / reject ----
            # The independent verifier reruns the session's claimed verification
            # evidence in a fresh subprocess; a diverging rerun rejects the claim
            # even when the in-path review would have approved or promoted it.
            decision = decide_for_session(
                posture_enum,
                session,
                goal.risk_tier,
                independent_verifier=build_session_verifier(timeout_seconds=timeout_seconds),
            )
            promoted = False
            if decision.action == ACTION_PROMOTE:
                try:
                    promoter(root, session_id=str(session.get("session_id") or ""))
                    promoted = True
                    state.counters["promoted"] += 1
                except Exception as exc:  # noqa: BLE001 - promotion failure is recorded, not fatal
                    logger.warning("evolve loop promotion failed for %s: %s", goal.id, exc)
                    state.counters["failed"] += 1
                    state.history.append(
                        history_item(
                            iteration=state.iteration,
                            goal=goal,
                            session=session,
                            decision_dict={"action": "reject", "reason": f"promotion error: {exc}"},
                            promoted=False,
                        )
                    )
                    state.current = None
                    save_loop_state(root, state)
                    continue
            elif decision.action == ACTION_APPROVE:
                state.pending_approvals.append(make_pending_approval(goal, session, decision.reason))
                state.counters["held"] += 1
            else:  # ACTION_REJECT
                if "no changes" in decision.reason:
                    state.counters.setdefault("no_change", 0)
                    state.counters["no_change"] += 1
                else:
                    state.counters["rejected"] += 1

            state.history.append(
                history_item(
                    iteration=state.iteration,
                    goal=goal,
                    session=session,
                    decision_dict=decision.to_dict(),
                    promoted=promoted,
                )
            )
            state.current = None
            save_loop_state(root, state)
            append_event(
                root,
                {
                    "type": "goal_done",
                    "iteration": state.iteration,
                    "goal_id": goal.id,
                    "action": decision.action,
                    "reason": decision.reason,
                    "promoted": promoted,
                },
                event_sink,
            )
            if spend_watchdog_verdicts:
                state.status = STATUS_STOPPED
                stop_reason = f"spend watchdog: {state.last_error}"
                save_loop_state(root, state)
                break

        if state.status == STATUS_RUNNING:
            state.status = STATUS_DONE
    except Exception as exc:  # noqa: BLE001 - capture, persist, and surface loop-level failures
        logger.exception("evolve loop crashed")
        state.status = STATUS_ERROR
        state.last_error = str(exc)
        stop_reason = f"error: {exc}"

    state.current = None
    state.finished_at = now_iso()
    save_loop_state(root, state)
    append_event(
        root,
        {"type": "loop_done", "status": state.status, "reason": stop_reason, "counters": dict(state.counters)},
        event_sink,
    )
    return state.to_dict()
