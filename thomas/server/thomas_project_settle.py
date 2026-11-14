"""Settling a Thomas project: the size rule, the check before your card, the second look, and the hand-in.

The public settle functions are re-exported by :mod:`thomas.server.thomas_project`.
Stop and steer holds, the handover lock, summaries, and issue reporting are looked up
there at call time, so existing callers and their patches still reach them.
"""

from __future__ import annotations

import contextvars
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import green_checkout, green_handoff, precard
from thomas.server import thomas_project as _tp
from thomas.server.precard import clocks
from thomas.server.routes.autopilot_goal import goal_text

log = _tp.log  # one logger for the whole Thomas project, as before the move


def _timed_review_verdict(execution_id: str, request: str, patch: str) -> Any:
    with clocks.stage("second_look"):
        return precard.review.review_verdict(execution_id, request, patch)


def keep_unfinished(execution_id: str, reason: str) -> dict[str, Any] | None:
    """Keep a nonempty green for ``green_checkout.KEPT_MAX_AGE_S`` and return its location and files."""
    green = green_checkout.find_green(execution_id)
    if green is None:
        return None
    try:
        files = green_checkout.changed_paths(green)
    except green_checkout.GreenUnavailable:
        log.warning("could not read the changes in green %s", execution_id, exc_info=True)
        return None
    if not files:
        return None
    green_checkout.mark_kept(green, reason)
    return {"execution_id": execution_id, "work": str(green.work), "files": files}


def settle_if_finished(
    root: Path, catalog_root: Path, cid: str, *, summary: str | None = None, expected_gen: list[Any] | None = None
) -> Path | None:
    """Settle a Thomas project's green -- called once the caller has already
    decided this turn is the one that finishes it (``evolve_agent_autopilot``'s
    ``decide()``, on Autopilot, or the first ok+completed turn below it).

    Requires an unsettled ``thomas_project`` record and an ``ok`` last agent turn.
    The caller decides completion; this function independently refuses failed turns.
    ``root`` holds the run's turns in the green; ``catalog_root`` survives the green --
    ``green_handoff.settle`` removes ``root`` entirely, including every turn
    of the conversation, so the conversation is copied there BEFORE
    settling, never after. ``settled_at`` is stamped on that surviving copy.

    Keep the registry pointing at ``root`` until a submission goes out or an
    empty green is genuinely gone. A failed hand-off retains the conversation
    for retry. A submission that went out still counts when removing its green
    fails (for example, while Windows holds a recently released folder).

    ``expected_gen`` is the finished turn a durable booking was made for (:mod:`thomas.server.hand_in_hold`).
    Nothing is checked or handed in unless that booking is still this conversation's, still checking, and its
    turn still current (:func:`_may_hand_in`): tested before the check, right after it, and after the second look
    under ``_handover_lock``, which is then held until the hand-off is done. A check that could not run raises ``precard.CheckUnavailable``
    unless it was turned off or the change is empty: never a card marked "Not checked".
    """
    with clocks.recording(catalog_root, cid):
        submission = _settle_unrecorded(root, catalog_root, cid, summary=summary, expected_gen=expected_gen)
        clocks.note("outcome", "handed_in" if submission is not None else "not_handed_in")
        clocks.note("submission", submission.name if submission is not None else "")
        return submission


def _may_hand_in(root: Path, catalog_root: Path, cid: str, token: list[Any], expected_gen: list[Any] | None) -> bool:
    """Whether this settle may still go on: its booking, when it has one, is intact and its turn still current."""
    from thomas.server import hand_in_hold  # it imports thomas_project

    booked = hand_in_hold.row(catalog_root, cid)
    if expected_gen is not None:
        if token != expected_gen or not booked or booked.get("gen") != token or booked.get("state") != "checking":
            return False
    elif not booked:
        return True  # no booking at all (the ratchet, a hand-in again): nothing here to supersede
    return hand_in_hold.still_current(root, catalog_root, cid, token)


def _settle_unrecorded(
    root: Path, catalog_root: Path, cid: str, *, summary: str | None, expected_gen: list[Any] | None
) -> Path | None:
    conversation = forge_code_store.load_conversation(root, cid)
    if conversation is None:
        return None
    project = conversation.get("thomas_project")
    if not isinstance(project, dict) or not project.get("execution_id"):
        return None
    if project.get("settled_at"):
        return None  # already settled -- never twice
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    last_agent = next((t for t in reversed(turns) if isinstance(t, dict) and t.get("role") == "agent"), None)
    if last_agent is None or not last_agent.get("ok"):
        return None  # never a failed run, whatever the caller decided
    if _tp.stop_requested(conversation) or _tp.held_steers(cid):
        return None  # you stopped it, or your steer waits for its next run: never handed in
    from thomas.server import hand_in_hold, self_project_already_passing  # hand_in_hold imports thomas_project

    execution_id = str(project["execution_id"])
    clocks.note("execution_id", execution_id)
    # Recheck the named test in its green only for planner-picked, note-only work.
    # An actual fix, a failed recheck, or an unavailable interpreter still takes the normal hand-in path.
    passing = self_project_already_passing.passing_test(catalog_root, cid, execution_id)
    if passing:
        token = hand_in_hold.generation(conversation)
        with _tp._handover_lock:
            if not _may_hand_in(root, catalog_root, cid, token, expected_gen) or _tp.stop_requested(conversation):
                return None
            if _tp.held_steers(cid):
                return None
            forge_code_store.write_conversation(catalog_root, conversation)
            green_handoff.settle(execution_id, promote=False)
            if green_checkout.find_green(execution_id) is not None:
                return None  # removal failed: keep the binding and retry instead of recording a false closure
            self_project_already_passing.remember(catalog_root, cid, passing)
            stored = forge_code_store.load_conversation(catalog_root, cid)
            if stored is not None and isinstance(stored.get("thomas_project"), dict):
                stored["thomas_project"]["settled_at"] = time.time()
                stored["thomas_project"]["summary"] = f"{passing} already passes; no code change or sign-in card."
                forge_code_store.write_conversation(catalog_root, stored)
            forge_code_store.mark_thomas_project_settled(catalog_root, cid)
            try:
                forge_code_projects.forget_conversation(catalog_root, cid)
            except OSError:
                log.warning("could not forget %s's green binding after settling", cid, exc_info=True)
            hand_in_hold.drop(catalog_root, cid, token)
        return None
    with clocks.stage("size_rule"):
        too_large = green_handoff.size_problems(execution_id)
    if too_large:  # Task 3b: the promoter would land it without this check, and nothing is handed in
        raise _tp.ChangeTooLarge("; ".join(too_large))
    token = hand_in_hold.generation(conversation)
    if not _may_hand_in(root, catalog_root, cid, token, expected_gen):
        return None
    # A held change can reuse its check only while the patch and dev tip still match.
    checked = precard.review.held_check(execution_id)
    clocks.note("reused_held_check", bool(checked))
    from thomas.server.routes import autopilot_sent_back

    request = autopilot_sent_back.review_request(goal_text(turns), conversation)
    review_result = None
    review_started = False
    if checked:
        clocks.note("patch_sha256", checked.patch_sha256)
    elif precard.review.turned_off():
        with clocks.stage("check_for_hand_in"):
            checked = precard.check_for_hand_in(execution_id)
        clocks.note("patch_sha256", checked.patch_sha256)
    else:
        # Stop the builder before freezing the patch; the reviewer reads that snapshot while tests run.
        green_handoff.end_green_processes(execution_id)
        green = green_checkout.find_green(execution_id)
        try:
            patch = green_checkout.green_patch(green) if green is not None else ""
        except (green_checkout.GreenUnavailable, OSError, subprocess.SubprocessError):
            # Leave an unreadable green to the check's normal unavailable result.
            patch = ""
        snapshot_sha = precard.patch_sha256(patch)

        with ThreadPoolExecutor(max_workers=1) as reviewers, precard.cancellable() as review_cancel:
            future = reviewers.submit(
                contextvars.copy_context().run, _timed_review_verdict, execution_id, request, patch
            )
            review_started = True
            try:
                with clocks.stage("check_for_hand_in"):
                    checked = precard.check_for_hand_in(execution_id)
            except BaseException:
                # Stop and join the read-only reviewer before releasing its turn.
                review_cancel.set()
                future.cancel()
                try:
                    with clocks.stage("second_look_wait"):
                        future.result()
                except Exception:
                    log.exception("the second look for green %s could not finish", execution_id)
                raise
            if (
                (checked.dev_tip and checked.patch) or (checked.cause == "off" and checked.patch_sha256)
            ) and checked.patch_sha256 != snapshot_sha:
                # The check may have used a different patch; never accept a verdict on old bytes.
                checked = precard.moved(checked, snapshot_sha)
            if checked.state in (precard.FAILED, precard.UNAVAILABLE) and checked.cause not in ("off", "empty"):
                review_cancel.set()
                future.cancel()
            try:
                with clocks.stage("second_look_wait"):
                    review_result = future.result()
            except precard.ReviewUnavailable as exc:
                review_result = exc
            except Exception as exc:
                log.exception("the second look for green %s could not finish", execution_id)
                review_result = precard.ReviewUnavailable(f"the second look could not finish: {exc}")
        clocks.note("patch_sha256", checked.patch_sha256)
    if not _may_hand_in(root, catalog_root, cid, token, expected_gen):
        return None  # a newer run, your Stop or a steer came during the check: no card and no repair round
    if checked.state == precard.UNAVAILABLE and checked.cause not in ("off", "empty"):
        raise precard.CheckUnavailable(checked.line, costly=checked.costly, cause=checked.cause)
    if checked.failed:  # one that will not apply to dev goes back the way a dev-moved refusal does
        raise (precard.ChangeDoesNotApply if checked.dev_moved else precard.ChangeFailedCheck)(checked.findings)
    autopilot_sent_back.reject_unchanged(conversation, cid, checked)
    # NOT SAFE returns to the team; unavailable holds the change. Neither reaches a card.
    if not review_started or not patch or (not checked.dev_tip and checked.cause != "off"):
        # A prior held check, empty snapshot, or synthetic check keeps its original review path.
        with clocks.stage("second_look"):
            checked = precard.review.second_look(execution_id, request, checked)
    elif isinstance(review_result, precard.ReviewUnavailable):
        precard.review.remember_unavailable(execution_id, checked)
        raise review_result
    else:
        with clocks.stage("review_apply"):
            checked = precard.review.apply_verdict(execution_id, checked, review_result)

    # Held from the last test until the card exists, and before anything is copied: a Stop or steer that came during
    # the second look leaves no catalog copy behind that would read "Handing the change to your approval card".
    with _tp._handover_lock:
        if not _may_hand_in(root, catalog_root, cid, token, expected_gen) or _tp.stop_requested(conversation):
            return None
        if _tp.held_steers(cid):
            return None
        # Handed in before (Task 3g, a refusal that cleared): the registry row went then, so keep what it had bound.
        earlier = _tp._project(forge_code_store.load_conversation(catalog_root, cid) or {})
        # Preserved BEFORE settling can remove `root` -- always, so a failed hand-off leaves a readable copy behind.
        forge_code_store.write_conversation(catalog_root, conversation)

        files = _tp._patch_files(execution_id)
        detail = _tp._change_summary(turns, last_agent, files)
        # A caller's own `summary` wins: the ratchet names the candidate it proved (ratchet/repair.py).
        summary = summary or " -- ".join(part for part in (_tp._subject(turns, files), detail) if part)
        chat = str(project.get("chat_session_id") or "") or cid  # the Chat that asked, when Chat started it
        bound = forge_code_projects.conversation_metadata(catalog_root, cid) or {}  # a repair round binds it again
        green_handoff.await_verdict(execution_id)  # Task 3b: its team may still need the green after this hand-in
        # The checked bytes themselves; "" for an empty change, so the green is not read again (it used to be None).
        patch = "" if checked.cause == "empty" else checked.patch or None  # None only when no check read the change
        with clocks.stage("hand_off"):
            submission = green_handoff.settle(
                execution_id, promote=True, summary=summary, chat=chat, checked=checked.line, patch=patch
            )
    green_kept = green_checkout.find_green(execution_id) is not None
    awaiting = green_handoff.awaiting_verdict(execution_id)

    if submission is None and green_kept:
        # The hand-off genuinely failed (its own submission could not be written) and kept the green rather than
        # lose a finished fix silently. Nothing here is settled, so the row is left exactly as it was -- forgetting
        # it would strand the live conversation at `root`, reachable only through the copy just made above.
        _tp.record_issue(
            surface="thomas_project",
            kind="settle_kept_green",
            message=f"settling Thomas project {execution_id} did not remove its green -- the hand-off failed",
            context={"conversation_id": cid, "execution_id": execution_id},
        )
        return submission

    # Either a submission went out, or nothing needed to (an empty patch) and the green is gone -- settled either way.
    stored = forge_code_store.load_conversation(catalog_root, cid)
    if stored is not None and isinstance(stored.get("thomas_project"), dict):
        # What the chat's task card reports: the change, and whether a card went out for it. Written BEFORE
        # the stamp: written after it, a card that checked in between read "settled, nothing submitted" and
        # said no file had changed (fix round 1, found by its tests under load).
        stored["thomas_project"].update(
            summary=summary,
            submission=submission.name if submission else "",
            checked=checked.line,  # what the cards and the listing say about the check (Task 3h)
            bound_settings=bound.get("settings") or earlier.get("bound_settings") or {},
        )
        forge_code_store.write_conversation(catalog_root, stored)
    forge_code_store.mark_thomas_project_settled(catalog_root, cid)
    try:
        forge_code_projects.forget_conversation(catalog_root, cid)
    except OSError:
        log.warning("could not forget %s's green binding after settling", cid, exc_info=True)
    if submission is not None and green_kept and not awaiting:  # kept for its verdict is not a leftover
        # The card already went out -- a `remove_green` that then failed (a Windows folder briefly held by a
        # process that just released it) is a leftover to sweep later, never a reason to report the hand-off failed.
        _tp.record_issue(
            surface="thomas_project",
            kind="settle_green_kept_after_submission",
            message=f"Thomas project {execution_id} settled, but its green could not be removed afterward",
            context={"conversation_id": cid, "execution_id": execution_id},
        )
    return submission


# The names thomas_project resolves here (its __getattr__).
NAMES = frozenset({"keep_unfinished", "settle_if_finished", "_may_hand_in", "_settle_unrecorded"})

__all__ = ["keep_unfinished", "settle_if_finished"]
