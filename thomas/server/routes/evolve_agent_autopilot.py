"""Autopilot continues a failed Build run itself, instead of waiting on you.

You asked: "he should never reply back with this didnt work say go and ill
do it again. autpilot shouldnt stop until it ha a finoisherfd product it
deems good failures will happena nd he must fix them and continue." Measured
2026-09-23: an Autopilot Build crashed twice ("build process exited 2") and
each time the conversation sat there, done, waiting for you to type "go" --
Autopilot (autonomy 5) never picked the failure back up on its own.

When the team says it finished, it is `done`, like ChatGPT: no done-check round
starts any more. A run that ends with a BLOCKED line (``autopilot_blockers``)
gets what it is missing within the permissions you gave, or, when only you can
give it, pauses for you at once. A conversation already mid-done-check
(:data:`REVIEW_PREFIX`) is still judged as before against :data:`DONE_BARS`.
Below Autopilot (autonomy 5) nothing here changes.

A provider-limit failure waits for ``autopilot_park`` to resume it, unless
executed self-continuations already exhausted the fuse. A wait alone never
counts, but recorded model output or tool activity before the limit does.
``autopilot_restart`` carries interrupted work on with its original request
(``run_text``). Interrupted work counts only with execution evidence; the
restart request alone cannot spend a run.

A Thomas project the promoter refuses because dev moved on (2026-09-24: two
finished projects, "the change no longer applies to dev") is `repair`: the same
green gets a new round, with dev already merged in by the server (Task 3h, ``green_rebase``), and the refusal in full
(:func:`repair_message`, :func:`start_repair`). So is a change that breaks the
repo's size rule, and one checked before your card and sent back with the
findings (Task 3d, ``POST /api/self/projects/{id}/send-back``). A repair round is
also subject to the execution-evidence fuse: it needs no message from you.
There is no limit on repair rounds; their count is shown, never enforced. What stops a project is no progress
(``autopilot_enough``): it then pauses for you (`enough`) at any autonomy, and your next message lifts the pause.

Every message built here is aimed at one goal, and that goal is everything you
asked for in the conversation -- your first request plus what your later
messages add or change, a later one winning where two conflict
(``autopilot_goal.goal_text``). It used to be your latest message alone, so a
"carry on" became the whole goal and the done check judged the work against it.

This module reads a stored conversation and decides what Autopilot does next
(:func:`decide`), builds the continuation message that hands the next run the
failure's own evidence (:func:`continuation_message`, with the other messages and
their prefixes, in :mod:`thomas.server.routes.autopilot_messages`), and starts that next
run once a run's slot is actually free (:func:`continue_after_turn`,
:func:`attach_after_run`). It never touches the run's runtime -- it only reads
what was already persisted and, on `continue` or `review`, calls the same
start hook Chat uses to launch a Build.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import (
    autopilot_blockers,
    autopilot_enough,
    autopilot_hold_tick,
    autopilot_park,
    hand_in_hold,
    precard,
    thomas_project,
)
from thomas.server.app_keys import APP_LOCAL_PORT, APP_PRAXIS_START_CODE_RUN
from thomas.server.app_keys import remember_port as remember_port
from thomas.server.issue_ledger import record_issue
from thomas.server.routes import autopilot_sent_back
from thomas.server.routes.autopilot_continuation_history import (
    actually_ran,
    ending_details,
    executed_runs_since_instruction,
    ran_continuations,
)
from thomas.server.routes.autopilot_goal import CONTINUATION_PREFIX, goal_text
from thomas.server.routes.autopilot_messages import (  # the messages and prefixes, re-exported under their old names
    DONE_BARS,  # noqa: F401 -- re-exported: tests and callers read ap.DONE_BARS
    REPAIR_PREFIX,
    RESTART_MARK,  # noqa: F401 -- re-exported
    RESTART_PREFIX,
    RESUME_PREFIX,
    REVIEW_PREFIX,
    STEER_PREFIX,
    TROUBLE_RESUME_PREFIX,
    continuation_message,
    repair_message,
    restart_message,  # noqa: F401 -- re-exported: autopilot_restart calls ap.restart_message
    resume_message,
    review_message,
    run_text,
    trouble_resume_message,
)
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS, slot_active, slot_running

log = logging.getLogger(__name__)

# Autopilot is autonomy level 5 -- the only level this module acts on.
AUTOPILOT = 5
# A fuse: after this many self-continuations with no new instruction from you,
# Autopilot stops rather than loop forever on work it cannot finish.
# There is no continuation limit: a project keeps going until it is done; how many runs it has used is shown, never enforced.
# Why a repair round started, in decide()'s reason: each refusal in its own words.
_REPAIR_WHY = {
    thomas_project.DEV_MOVED: "dev moved on under the change",
    thomas_project.TOO_LARGE: "it is too large",
    thomas_project.SENT_BACK: "it was checked and sent back",
}

_ISSUE_TAIL_CHARS = 200
_NO_RUN_ACTIVITY_RISK = "no run activity was recorded"
_STOPPED_OUTCOME = "stopped"
_FINISHED_OUTCOMES = ("completed", "conversation")
# The code both a same-conversation conflict and the concurrency ceiling
# answer with (evolve_agent_routes.py's `_start_run`) -- the signal that the
# refusal is transient and worth a short retry, not a real failure.
_BUSY_CODE = "agent_already_running"
_START_RETRY_LIMIT = 5
_START_RETRY_DELAY_S = 2.0
# A module-local alias for the retry wait, so a test can slow-motion only OUR
# retry loop by patching this name -- patching `asyncio.sleep` itself patches
# it for the whole process, every other coroutine on the loop included.
_sleep = asyncio.sleep


@dataclass(frozen=True)
class Decision:
    """What Autopilot does next, and why. `message` is set for `continue`, `review` and `wait` (the run that
    resumes after the limit resets); `retry_at` (Unix seconds) and `provider` only for `wait`."""

    action: str  # "done" | "continue" | "review" | "repair" | "wait" | "limited" | "spent" | "stall" | "cap" | "off"
    # ... or "enough": no progress, so it is paused for you (autopilot_enough) and nothing starts until you write
    reason: str
    message: str = ""
    retry_at: float | None = None
    provider: str = ""
    start_pending: bool = False
    why: str = ""  # for `enough`: the pause's why on the project's record ("blocked"); "" is a done-check pause


def _digits_removed(text: Any) -> str:
    return re.sub(r"\d+", "", str(text or ""))


def _agent_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in turns if isinstance(t, dict) and t.get("role") == "agent"]


def _last_agent_turn(turns: list[dict[str, Any]]) -> dict[str, Any] | None:
    agents = _agent_turns(turns)
    return agents[-1] if agents else None


def _goal(turns: list[dict[str, Any]]) -> str:
    """Everything you asked for in this conversation, as one text (``autopilot_goal.goal_text``).

    Never the latest instruction alone: a "carry on" or an "also make the button blue" adds to your first
    request instead of replacing it, so every message built below still carries what you asked for first.
    """
    return goal_text(turns)


def _last_user_turn(turns: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The last `role == "user"` turn, self-continuation or not."""
    for turn in reversed(turns):
        if isinstance(turn, dict) and turn.get("role") == "user":
            return turn
    return None


def _continuation_count(turns: list[dict[str, Any]]) -> int:
    """Self-continuations with a recorded run since the last instruction."""
    return len(ran_continuations(turns))


def _cap_explanation(turns: list[dict[str, Any]]) -> str:
    runs = ran_continuations(turns)
    return f"{len(runs)} self-continuation runs already tried with no new instruction. Endings: {ending_details(runs)}"


def _has_no_run_activity_risk(turn: dict[str, Any]) -> bool:
    report = turn.get("report") if isinstance(turn.get("report"), dict) else {}
    risks = report.get("open_risks") if isinstance(report.get("open_risks"), list) else []
    return any(isinstance(r, dict) and r.get("risk") == _NO_RUN_ACTIVITY_RISK for r in risks)


def _same_stall_signature(a: dict[str, Any], b: dict[str, Any]) -> bool:
    sig_a = (a.get("outcome"), _digits_removed(a.get("reason")))
    sig_b = (b.get("outcome"), _digits_removed(b.get("reason")))
    return (
        sig_a == sig_b
        and actually_ran(a)
        and actually_ran(b)
        and a.get("changed_files") == []
        and b.get("changed_files") == []
        and _has_no_run_activity_risk(a)
        and _has_no_run_activity_risk(b)
    )


def decide(conversation: dict[str, Any]) -> Decision:
    """Read the stored conversation only, and say what Autopilot does next."""
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    requested = (conversation.get("settings") or {}).get("requested") or {}
    last_agent = _last_agent_turn(turns)

    if thomas_project.stop_requested(conversation):  # Stop on Chat's card, even between rounds (Task 4 M5)
        return Decision("off", "you stopped it")
    if paused := autopilot_enough.standing(conversation):  # no progress: paused for you, at any autonomy
        return Decision("enough", paused)
    spent = thomas_project.repairs_spent(conversation)
    if spent:  # Task 3b: sent back to its team as often as it may be
        return Decision("spent", spent)
    due = thomas_project.repair_due(conversation)
    if due is not None:  # Task 3b: at any autonomy -- finishing the hand-in you asked for, not retrying a failure
        goal = _goal(turns)
        why = _REPAIR_WHY.get(str(due.get("why") or ""), "it came back")
        reason = f"repair round {due.get('round')}: {why}"
        return Decision("repair", reason, autopilot_sent_back.with_findings(repair_message(goal, due), conversation))
    if requested.get("autonomy_level") != AUTOPILOT:
        return Decision("off", "autonomy is not Autopilot")
    if last_agent is not None and last_agent.get("outcome") == _STOPPED_OUTCOME:
        return Decision("off", "the run was stopped")
    effort = str(requested.get("reasoning_effort") or "medium")
    pause = autopilot_park.quota_pause(last_agent, tries=autopilot_park.limit_streak(_agent_turns(turns)))
    if pause is not None:  # waiting without execution evidence does not spend a run
        held = autopilot_park.held_reason(conversation, pause)  # a pause that cannot end by itself says so
        if held:
            return Decision("limited", held)
        message = autopilot_sent_back.failed_round_message(
            resume_message(_goal(turns), last_agent or {}, pause.provider), conversation
        )
        return Decision("wait", autopilot_park.paused_text(pause), message, pause.retry_at, pause.provider)
    pause = autopilot_park.trouble_pause(last_agent, tries=autopilot_park.trouble_streak(_agent_turns(turns)))
    if pause is not None:
        held = autopilot_park.held_reason(conversation, pause)
        if held:
            return Decision("limited", held)
        message = autopilot_sent_back.failed_round_message(
            trouble_resume_message(_goal(turns), last_agent or {}, pause.provider), conversation
        )
        return Decision("wait", autopilot_park.paused_text(pause), message, pause.retry_at, pause.provider)
    if (blocked := autopilot_blockers.judge(turns, _goal(turns))) is not None:  # BLOCKED: get it, or ask you
        message = autopilot_sent_back.failed_round_message(blocked.message, conversation) if blocked.message else ""
        return Decision(blocked.action, blocked.reason, message, why=blocked.why)
    if last_agent is not None and last_agent.get("ok") and last_agent.get("outcome") in _FINISHED_OUTCOMES:
        last_user = _last_user_turn(turns)
        if last_user is None or not run_text(last_user).startswith(REVIEW_PREFIX):
            return Decision("done", "the team said it finished")  # no done-check round: finished is done
        if not last_agent.get("changed_files"):  # a done check started before 2026-11-13 is judged as it was
            return Decision("done", f"Autopilot judged it done at the {effort} bar")
        if tweaking := autopilot_enough.tweaking(turns):  # done checks that keep changing files: paused for you
            return Decision("enough", tweaking)
        return Decision(
            "review",
            f"finished: checking it against the {effort} bar",
            autopilot_sent_back.with_findings(
                review_message(_goal(turns), last_agent, effort), conversation, review=True
            ),
        )

    agents = executed_runs_since_instruction(turns)
    if len(agents) >= 2 and _same_stall_signature(agents[-2], agents[-1]):
        return Decision("stall", "the same machinery crash happened twice in a row")

    last_user = _last_user_turn(turns)
    if (
        last_agent is not None
        and last_user is not None
        and run_text(last_user).startswith(REVIEW_PREFIX)
        and not last_agent.get("changed_files")
    ):
        effort = str(requested.get("reasoning_effort") or "medium")
        return Decision(
            "review",
            f"failed done check: checking it again at the {effort} bar",
            autopilot_sent_back.with_findings(
                review_message(_goal(turns), last_agent, effort), conversation, review=True
            ),
        )

    message = autopilot_sent_back.failed_round_message(
        continuation_message(_goal(turns), last_agent or {}), conversation
    )
    return Decision("continue", "the run did not finish", message)


def _record_stall(conversation: dict[str, Any], cid: str) -> None:
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    last_two = executed_runs_since_instruction(turns)[-2:]
    reasons = [str(t.get("reason") or "") for t in last_two]
    tails = [str(t.get("transcript") or "")[-_ISSUE_TAIL_CHARS:] for t in last_two]
    record_issue(
        surface="autopilot",
        kind="autopilot_stall",
        message="the same machinery crash happened twice; stopping instead of asking you to say go",
        context={
            "conversation_id": cid,
            "reason_1": reasons[0] if len(reasons) > 0 else "",
            "reason_2": reasons[1] if len(reasons) > 1 else "",
            "transcript_tail_1": tails[0] if len(tails) > 0 else "",
            "transcript_tail_2": tails[1] if len(tails) > 1 else "",
        },
    )


def _record_cap(conversation: dict[str, Any], cid: str, explanation: str = "") -> None:
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    runs = ran_continuations(turns)
    record_issue(
        surface="autopilot",
        kind="autopilot_cap",
        message=f"Autopilot stopped after {len(runs)} runs of self-continuations with no new instruction from you",
        context={
            "conversation_id": cid,
            "run_endings": (explanation or ending_details(runs))[:_ISSUE_TAIL_CHARS],
        },
    )
    # The issue ledger truncates each context value at 200 characters: one
    # entry per run preserves every ending even when all twelve are counted.
    for index, turn in enumerate(runs, 1):
        record_issue(
            surface="autopilot",
            kind="autopilot_cap_run",
            message=f"Self-continuation run {index} of {len(runs)} ended",
            context={
                "conversation_id": cid,
                "run": str(index),
                "outcome": str(turn.get("outcome") or "unknown"),
                "reason": str(turn.get("reason") or "no reason recorded"),
            },
        )


def _record_start_refused(conversation: dict[str, Any], cid: str, status: int | None, payload: dict[str, Any]) -> None:
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    last_agent = _last_agent_turn(turns) or {}
    record_issue(
        surface="autopilot",
        kind="autopilot_start_refused",
        message=f"Autopilot's continuation for conversation {cid} was refused (status {status})",
        context={
            "conversation_id": cid,
            "status": str(status),
            "code": str(payload.get("code") or ""),
            "run_id": str(last_agent.get("run_id") or ""),
        },
    )


async def _start_continuation(
    app: Any, project_root: Path, catalog_root: Path, conversation: dict[str, Any], cid: str, decision: Decision
) -> bool | None:
    """True means accepted, None means still busy, and False means refused or stale."""
    start = app.get(APP_PRAXIS_START_CODE_RUN)
    port = app.get(APP_LOCAL_PORT)
    if start is None or not port:
        log.warning("autopilot: cannot continue conversation %s -- no start hook or local port bound", cid)
        return False
    requested = (conversation.get("settings") or {}).get("requested") or {}
    # Steering you sent from Chat while no run was live goes first (Task 4 fix round 1, I2).
    steers = thomas_project.held_steers(cid)
    body = {**requested, "conversation_id": cid, "message": thomas_project.steering_message(steers, decision.message)}
    # A server continuation has no composer to retry an accepted-but-queued send.
    body.pop("queue_if_busy", None)
    # What "no new instruction since this decision" means, so a retry after a
    # busy wait can tell it apart from "you typed something while it waited".
    original_goal = _goal(conversation.get("turns") or [])
    status: int | None = None
    payload: dict[str, Any] = {}
    for attempt in range(1, _START_RETRY_LIMIT + 1):
        if thomas_project.stop_requested(conversation):  # you pressed Stop while this was deciding or waiting
            return False
        try:
            status, raw_payload = await start(body, port=port)
        except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError):
            log.exception("autopilot: continuation request for conversation %s raised", cid)
            return False
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        # A busy answer (this conversation's slot not yet pruned, or every
        # concurrency slot taken) is transient -- worth a short wait, not a
        # reason to give up and leave you to notice and retry it yourself.
        if status == 409 and payload.get("code") == _BUSY_CODE and attempt < _START_RETRY_LIMIT:
            await _sleep(_START_RETRY_DELAY_S)
            # Reload and re-decide before retrying: the wait just gave you
            # time to type something real, or gave the run itself time to
            # change what Autopilot should do next. Retrying blind would fire
            # this stale continuation message on top of either. A
            # conversation that vanished (deleted while this waited) is the
            # same signal -- stop, start nothing.
            fresh = _load_joined_conversation(project_root, catalog_root, cid)
            if fresh is None:
                return False
            fresh_decision = decide(fresh)
            fresh_goal = _goal(fresh.get("turns") or [])
            # The body was built before waiting; a changed decision or goal makes it stale.
            stale = fresh != conversation if decision.action == "restart" else fresh_decision != decision
            if stale or fresh_goal != original_goal:
                return False
            continue
        break
    if status is not None and 200 <= status < 300:
        thomas_project.drop_steers(cid, len(steers))
        interrupt_for_steer(app, cid)  # N1: a steer that arrived while this start was in flight rides it now
        return True
    if status == 503 and payload.get("code") == "reload_draining":
        from thomas.server.autopilot_restart import defer_until_reload

        defer_until_reload(catalog_root, conversation, cid)
        return False
    _record_start_refused(conversation, cid, status, payload)
    if payload.get("code") == _BUSY_CODE:
        return None
    return False


async def _start_steered_round(app: Any, conversation: dict[str, Any], cid: str, catalog_root: Path) -> None:
    """Start the next run with the steering you sent from Chat (Task 4 fix round 1, I2).

    For a run stopped for your steering, or where Autopilot would otherwise stop or settle. It is your
    instruction, not a self-continuation, so it runs at any autonomy level; the steers are dropped only
    once a run carrying them has started.
    """
    start, port, steers = app.get(APP_PRAXIS_START_CODE_RUN), app.get(APP_LOCAL_PORT), thomas_project.held_steers(cid)
    if start is None or not port or not steers:
        log.warning("autopilot: cannot start conversation %s's steered run -- no start hook or port bound", cid)
        return
    goal = _goal(conversation.get("turns") or [])
    rest = "Apply it first, then carry on until the goal is met and its checks pass."
    message = thomas_project.steering_message(steers, f"{STEER_PREFIX} toward the goal: {goal}\n\n{rest}")
    requested = (conversation.get("settings") or {}).get("requested") or {}
    body, status, payload = {**requested, "conversation_id": cid, "message": message}, None, {}
    for attempt in range(1, _START_RETRY_LIMIT + 1):
        if thomas_project.stop_requested(conversation):
            return
        try:
            status, raw_payload = await start(body, port=port)
        except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError):
            log.exception("autopilot: the steered run for conversation %s raised", cid)
            return
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        if status == 409 and payload.get("code") == _BUSY_CODE and attempt < _START_RETRY_LIMIT:
            await _sleep(_START_RETRY_DELAY_S)
            continue
        break
    if status is not None and 200 <= status < 300:
        thomas_project.drop_steers(cid, len(steers))
        interrupt_for_steer(app, cid)
        return
    if status == 503 and payload.get("code") == "reload_draining":
        from thomas.server.autopilot_restart import defer_until_reload

        defer_until_reload(catalog_root, conversation, cid)
        return
    _record_start_refused(conversation, cid, status, payload)


def interrupt_for_steer(app: Any, cid: str) -> bool:
    """Stop the conversation's live run for steering held for it, the way Build's own steer route does.

    Build's recorder files the run "stopped for your steering update", and ``after_run`` starts the next one
    with the steering first. Nothing happens when no steering is held or no run is live (the next
    ``after_run`` carries it then). Used by Chat's steer (``chat_self_project``) and, for a steer that arrived
    while a start was in flight, right after that start (Task 4 round 2, N1).
    """
    from thomas.server.routes.evolve_agent_runtime import _kill_tree, _mark_steer_requested

    slot = (app.get(APP_EVOLVE_AGENT_RUNS) or {}).get(cid)
    if not thomas_project.held_steers(cid) or not slot_running(slot):
        return False
    proc = slot["session"]["proc"]
    _mark_steer_requested(proc)
    try:
        asyncio.get_running_loop().run_in_executor(None, _kill_tree, proc)
    except RuntimeError:  # no loop in this thread: stop it right here
        _kill_tree(proc)
    return True


def _load_joined_conversation(project_root: Path, catalog_root: Path, cid: str) -> dict[str, Any] | None:
    """The conversation `decide` can actually read, or ``None``.

    `forge_code_store` persists only turns -- the requested settings (which
    carry the autonomy level `decide` reads) live in the catalog's project
    registry, and are joined at read time exactly the way the conversation GET
    route joins them (`forge_code_projects.conversation_metadata(catalog_root,
    cid)["settings"]`). Reading the raw store record alone always sees no
    requested autonomy level, so Autopilot would decide `off` every time --
    and, after fix round 1, `_thomas_project_should_settle` would silently
    fall through to its below-Autopilot branch instead. One join, shared by
    every caller that needs it, is what keeps that from happening twice.
    """
    return _joined(catalog_root, cid, forge_code_store.load_conversation(project_root, cid))


def _joined(catalog_root: Path, cid: str, conversation: dict[str, Any] | None) -> dict[str, Any] | None:
    """``conversation`` joined with its requested settings from the catalog's registry (see above)."""
    if conversation is None:
        return None
    metadata = forge_code_projects.conversation_metadata(catalog_root, cid) or {}
    return {**conversation, "settings": metadata.get("settings") or {}}


async def continue_after_turn(app: Any, project_root: Path, catalog_root: Path, cid: str) -> Decision:
    """Decide from the stored conversation and act: start, record, or do nothing."""
    conversation = _load_joined_conversation(project_root, catalog_root, cid)
    if conversation is None:
        return Decision("off", "conversation not found")
    decision = decide(conversation)
    # `wait` parks it until the limit resets, and this server's park loop resumes it; any other answer ends a park.
    autopilot_park.record(project_root, catalog_root, cid, conversation, decision, port=app.get(APP_LOCAL_PORT) or 0)
    if decision.action in ("continue", "review", "repair"):
        if not await _start_continuation(app, project_root, catalog_root, conversation, cid, decision):
            return replace(decision, start_pending=True)
    elif decision.action == "enough":  # stamped once (and its issue recorded), so a restart leaves it alone too
        port = app.get(APP_LOCAL_PORT) or 0
        why = decision.why or "done checks"
        await asyncio.to_thread(
            autopilot_enough.stamp, project_root, catalog_root, cid, why=why, words=decision.reason, port=port
        )
    elif decision.action == "stall":
        _record_stall(conversation, cid)
    elif decision.action == "cap":
        _record_cap(conversation, cid, decision.reason)
    elif decision.action == "limited":
        record_issue(
            surface="autopilot", kind="autopilot_limit_held", message=decision.reason, context={"conversation_id": cid}
        )
    return decision


def attach_after_run(app: Any, task: asyncio.Task[Any], project_root: Path, catalog_root: Path, cid: str) -> None:
    """Schedule Autopilot's continuation once a run's drain task is fully done.

    The done-callback runs after the drain task finishes, allowing `_prune_runs`
    to release its active slot before another run starts.
    """

    def _on_done(done_task: asyncio.Task[Any]) -> None:
        if done_task.cancelled():
            return
        try:
            if done_task.exception() is not None:
                return
        except asyncio.CancelledError:
            return
        from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN

        if app.get(APP_LANDED_CODE_DRAIN):
            try:
                from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt

                conversation = _load_joined_conversation(project_root, catalog_root, cid) or {}
                user = next(
                    (turn for turn in reversed(conversation.get("turns") or []) if turn.get("role") == "user"), {}
                )
                request_id = str(user.get("request_id") or "")
                receipt = _action_receipt(catalog_root, "run", request_id) if request_id else None
                if receipt and receipt.get("state") == "completed":
                    _save_action_receipt(catalog_root, "run", request_id, {**receipt, "state": "after_run_pending"})
                    return
            except (OSError, TypeError, ValueError):
                log.exception("autopilot: could not save reload continuation for %s", cid)
        from thomas.server.routes.autopilot_handoff import finish_handoff

        asyncio.ensure_future(finish_handoff(app, project_root, catalog_root, cid))

    task.add_done_callback(_on_done)


def _thomas_project_should_settle(decision: Decision, conversation: dict[str, Any]) -> bool:
    """Whether THIS turn is the one that hands a Thomas project's green to your card.

    A pure predicate over the decision `decide()` already made and the turn
    itself -- never a match on `decision.reason`'s text (fix round 1: a
    string match is exactly the kind of check a later wording change quietly
    breaks). On Autopilot, only `done` settles: a finished run (`completed`,
    or a `conversation`-outcome reply such as an old done check's), so outcome
    is not checked here -- `decide` already read it. Below Autopilot, `decide` always answers `off` (its
    very first check, before it ever looks at how the run finished), so the
    turn is the only signal left: the first `ok`+`completed` pass, same as
    before there was a done check at all. A stopped run never settles, on
    any autonomy level -- you pressed Stop, not "ship what's there". Nor
    does a project on its way back to its team, or out of repair rounds.
    """
    if decision.action in ("repair", "spent", "enough"):
        return False
    last_agent = _last_agent_turn(conversation.get("turns") if isinstance(conversation.get("turns"), list) else [])
    if last_agent is None or last_agent.get("outcome") == _STOPPED_OUTCOME:
        return False
    project = conversation.get("thomas_project") if isinstance(conversation.get("thomas_project"), dict) else {}
    # A ratchet repair (thomas/server/ratchet/repair.py) is proven by the ratchet, which then settles it with a
    # summary naming the candidate: Autopilot's done check is where the team stops, not where the change lands.
    if project.get("hold_settle"):
        return False
    # Stopped from Chat's card, or your steering still waits for its run: neither is a finished project.
    if thomas_project.stop_requested(conversation) or thomas_project.held_steers(str(conversation.get("id") or "")):
        return False
    requested = (conversation.get("settings") or {}).get("requested") or {}
    if requested.get("autonomy_level") == AUTOPILOT:
        return decision.action == "done"
    return bool(last_agent.get("ok")) and last_agent.get("outcome") == "completed"


async def _settle_thomas_project(
    project_root: Path, catalog_root: Path, cid: str, *, app: Any = None, gen: list[Any] | None = None
) -> None:
    """Book the finished turn, check it off the event loop, then let the conversation that asked see the card.

    `thomas_project.settle_if_finished` runs `green_handoff.settle`, which
    measured 1.6-2.1s for `remove_green` alone plus the cage IPC's own poll
    on a real green. It runs on the check threads (`precard.workers.off_the_loop`):
    not on the event loop other conversations need, and not on the default
    threads request handlers use. `self_change_status.
    follow` needs a running loop of its own (it polls for your verdict), so
    it is only started here, back on the loop, once settling itself is done.
    Task 4: the cards go to the Chat that asked for the change when Chat
    started the project (`thomas_project.chat_to_follow`); a Build
    conversation id is a session no question panel ever polls.

    Task 3b: a change that breaks the size rule is not handed in; it goes back
    to its team. A hand-in's verdict is followed, and a refusal because dev
    moved on sends the change back to its team too (:func:`_follow_verdict`).
    Task 3h: so does a change the check before your card found something in --
    it never reaches the card (``precard.ChangeFailedCheck``). Caught before
    the broad handler below, which would otherwise swallow it as a RuntimeError.

    The try is booked on a durable record first (``hand_in_hold.book``): no booking, no hand-in. A check or
    second look that cannot run (``precard.CheckUnavailable``, ``precard.ReviewUnavailable``) holds the change
    there instead of handing it in unchecked, and :mod:`thomas.server.autopilot_hold_tick` tries it again; that
    retry passes ``gen``, the turn it booked, and already holds the check's claim across servers.
    """
    from thomas.server import self_change_status

    retry = gen is not None
    if not self_change_status.claim(cid):
        if not retry:  # another hand-in of it runs in this server: wait on the record, not in memory
            port = autopilot_hold_tick.port_of(app)
            await asyncio.to_thread(hand_in_hold.book, project_root, catalog_root, cid, port=port, claim_busy=True)
        return
    submission = None
    unwritten: Exception | None = None  # the unavailable step whose hold a restart may cut off mid-write
    try:
        if not retry:
            port = autopilot_hold_tick.port_of(app)
            row = await asyncio.to_thread(hand_in_hold.book, project_root, catalog_root, cid, port=port)
            if row is None or row.get("state") != "checking":
                return  # no durable booking for this turn means no hand-in
            gen = row["gen"]
        with contextlib.nullcontext(True) if retry else hand_in_hold.check_claim(catalog_root, cid) as acquired:
            if not acquired:  # another server checks it: held, no strike, due in 900 s; that try then stands down
                why = "another server is checking this change"
                hold = hand_in_hold.hold
                await asyncio.to_thread(hold, project_root, catalog_root, cid, "check", why, costly=False, gen=gen)
                return
            settle = thomas_project.settle_if_finished
            submission = await precard.workers.off_the_loop(settle, project_root, catalog_root, cid, expected_gen=gen)
        chat = await asyncio.to_thread(thomas_project.chat_to_follow, catalog_root, cid) if submission else cid
        if submission is not None or await asyncio.to_thread(thomas_project.settled_record, catalog_root, cid):
            await asyncio.to_thread(hand_in_hold.drop, catalog_root, cid, gen)
    except (thomas_project.ChangeTooLarge, precard.ChangeFailedCheck) as exc:  # a NOT SAFE second look too
        if await asyncio.to_thread(hand_in_hold.still_current, project_root, catalog_root, cid, gen):
            large = isinstance(exc, thomas_project.ChangeTooLarge)
            why = thomas_project.TOO_LARGE if large else failed_check_reason(exc)
            await asyncio.to_thread(hand_in_hold.drop, catalog_root, cid, gen)
            stalled = autopilot_enough.repairs_stalled  # five rounds with no fewer failing tests: paused for you
            if large or not await asyncio.to_thread(stalled, project_root, catalog_root, cid, why, str(exc)):
                await start_repair(app, project_root, catalog_root, cid, why=why, detail=str(exc))
        return  # superseded by your Stop, a steer or a newer run: no repair round
    except precard.workers.Restarting:  # a RuntimeError too: no check starts while a restart is pending, so it waits
        await asyncio.to_thread(hand_in_hold.wait_for_restart, catalog_root, cid, gen)
        return
    except precard.ReviewUnavailable as exc:  # before the broad handler: it is a RuntimeError, and it is a hold
        unwritten = exc
        await asyncio.to_thread(hand_in_hold.hold_unavailable, project_root, catalog_root, cid, exc, gen=gen)
        unwritten = None
        return
    except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError, MemoryError) as exc:
        log.exception("autopilot: settling the Thomas project for conversation %s failed", cid)
        why = str(exc) or type(exc).__name__  # a MemoryError says nothing: its name is the reason shown
        await asyncio.to_thread(hand_in_hold.hold, project_root, catalog_root, cid, "hand-in", why, gen=gen)
        return
    finally:
        try:
            if unwritten is not None:  # cancelled while its own hold was written: that hold, never the fallback's
                hold = hand_in_hold.hold_unavailable
                await asyncio.to_thread(hold, project_root, catalog_root, cid, unwritten, gen=gen)
            await asyncio.to_thread(autopilot_hold_tick.hold_if_unfinished, project_root, catalog_root, cid, gen)
        finally:
            self_change_status.release(cid)
    if submission is not None:
        record = await asyncio.to_thread(thomas_project.settled_record, catalog_root, cid) or {}
        note = str(record.get("checked") or "")
        follow = _follow_verdict(app, project_root, catalog_root, cid, submission.name, chat, note)
        asyncio.create_task(follow, name=f"thomas-project:{submission.name}")


def failed_check_reason(exc: Exception) -> str:
    """The repair round for a change the check before your card failed.

    One that will not apply to dev is a dev-moved round, so the server merges dev into its copy and names the
    files still holding conflict markers (``green_rebase``); any other finding is sent back as it is.
    """
    return thomas_project.DEV_MOVED if isinstance(exc, precard.ChangeDoesNotApply) else thomas_project.SENT_BACK


async def _follow_verdict(
    app: Any, project_root: Path, catalog_root: Path, cid: str, sid: str, chat: str, checked: str = ""
) -> None:
    """Show the promoter's cards in the chat; a refusal because dev moved on sends the change back to its team, and one
    for the running copy's uncommitted work hands the same change in again once that work is committed (Task 3g).

    ``checked`` is what the check before the card found (Task 3h), shown on the card itself."""
    from thomas.server import self_change_status

    status = await self_change_status.follow(sid, chat, checked=checked)
    if status != "refused" or app is None:
        return
    verdict = await asyncio.to_thread(self_change_status.read_verdict, sid) or {}
    if self_change_status.dev_moved(verdict):
        detail = self_change_status.refusal_text(verdict)
        await start_repair(app, project_root, catalog_root, cid, why=thomas_project.DEV_MOVED, detail=detail, sid=sid)
    elif files := self_change_status.uncommitted_files(verdict):
        await self_change_status.wait_then_hand_in(app, project_root, catalog_root, cid, sid, files)


async def start_repair(
    app: Any, project_root: Path, catalog_root: Path, cid: str, *, why: str, detail: str, sid: str = ""
) -> Decision | None:
    """Send a refused, too-large or sent-back change back to its team, in the same green, through the continuation path.

    It needs no message from you and is not a continuation (the fuse counts from it); there is no round limit.
    Never raises into the loop.
    """
    if app is None:
        return None
    try:
        number = await asyncio.to_thread(
            thomas_project.prepare_repair, project_root, catalog_root, cid, why=why, detail=detail, sid=sid
        )
        if number:
            from thomas.server.routes.autopilot_handoff import start_repair_handoff

            return await start_repair_handoff(app, project_root, catalog_root, cid)
    except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError):
        log.exception("autopilot: the repair round for conversation %s did not start", cid)
        return None
    from thomas.server import thomas_project_successor

    try:
        successor = await thomas_project_successor.carry_exhausted(
            app, project_root, catalog_root, cid, why=why, detail=detail, sid=sid
        )
    except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError):
        log.exception("autopilot: could not carry exhausted repair for %s", cid)
        successor = None
    if successor is None:
        record_issue(
            surface="autopilot",
            kind="autopilot_repairs_spent",
            message="a Thomas project could not start its successor after its repair rounds",
            context={"conversation_id": cid, "why": why, "detail": detail[:_ISSUE_TAIL_CHARS]},
        )
    return None


async def after_run(app: Any, project_root: Path, catalog_root: Path, cid: str) -> Decision | None:
    """Decide before settling, preserving pending starts for restart recovery.

    Only `done` settles on Autopilot; below Autopilot, a completed turn can
    settle. Held steering starts before settlement when no run is active.
    """
    try:
        decision = await continue_after_turn(app, project_root, catalog_root, cid)
    except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError):
        log.exception("autopilot: continuation failed for conversation %s", cid)
        return None

    try:
        conversation = await asyncio.to_thread(_load_joined_conversation, project_root, catalog_root, cid)
    except OSError:
        conversation = None
    # Held steering starts only when no continuation has already started a run.
    idle = not slot_active((app.get(APP_EVOLVE_AGENT_RUNS) or {}).get(cid))
    steered = idle and thomas_project.held_steers(cid)
    if conversation is not None and steered and not thomas_project.stop_requested(conversation):
        await _start_steered_round(app, conversation, cid, catalog_root)
        decision = replace(decision, start_pending=bool(thomas_project.held_steers(cid)))
    elif idle and conversation is not None and _thomas_project_should_settle(decision, conversation):
        await _settle_thomas_project(project_root, catalog_root, cid, app=app)  # never under a run that started

    return decision
