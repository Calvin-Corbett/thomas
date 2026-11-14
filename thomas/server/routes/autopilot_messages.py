"""The messages Autopilot starts a run with, and the prefixes that tell its turns apart from yours.

Moved out of ``evolve_agent_autopilot`` unchanged on 2026-09-25, when that module reached 799 lines and the next
edit to it would have broken the size rule. ``evolve_agent_autopilot`` imports every name back, so
``ap.REVIEW_PREFIX``, ``ap.repair_message`` and the rest still work.
"""

from __future__ import annotations

from typing import Any

from thomas.core.acceptance_notes import THOMAS_NOTES_END, THOMAS_NOTES_START
from thomas.core.autonomy import AUTOPILOT_BLOCKED_RULE
from thomas.server import green_rebase, thomas_project
from thomas.server.routes.autopilot_goal import CONTINUATION_PREFIX

# CONTINUATION_PREFIX (imported from autopilot_goal) marks a user turn this module wrote, so the fuse can
# tell "Thomas kept retrying" apart from "you asked for something new", and the goal can leave it out.
# Every prefix below is built on it.
# A done check on a finished run. No new one starts since 2026-11-13 (a finished run is done); the prefix stays so a
# conversation already mid-done-check is still judged as before. Starts with CONTINUATION_PREFIX on purpose:
# the fuse counts a review round as a self-continuation, and the goal
# skips it the same way it skips a plain continuation.
REVIEW_PREFIX = f"{CONTINUATION_PREFIX}: done check"
# The run that resumes after a usage-limit pause (autopilot_park). It starts with
# CONTINUATION_PREFIX, so the goal skips it, but the fuse never counts it:
# waiting out a limit is not a retry.
RESUME_PREFIX = f"{CONTINUATION_PREFIX}: resuming after the usage limit"
TROUBLE_RESUME_PREFIX = f"{CONTINUATION_PREFIX}: resuming after provider trouble"
# The run that picks up a run a server restart stopped (autopilot_restart, Task 3f). It starts with
# CONTINUATION_PREFIX, so _last_goal_turn skips it, and the fuse never counts it: a restart is not a retry. The
# stopped run's own message follows RESTART_MARK in full, and run_text reads it back.
RESTART_PREFIX = f"{CONTINUATION_PREFIX}: resuming after a restart"
RESTART_MARK = "The stopped run's message, in full:\n"
# A run started for steering you sent from Chat when no Autopilot round was coming (Task 4 round 2, N2). It
# starts with CONTINUATION_PREFIX so the goal stays your own request instead of nesting the steer inside it.
STEER_PREFIX = f"{CONTINUATION_PREFIX} with your steering update"
# A refused Thomas project's round back with its team (Task 3b). It starts with CONTINUATION_PREFIX, so the goal
# stays your request, but it is new work, not a retry: the fuse counts continuations only from it.
REPAIR_PREFIX = thomas_project.REPAIR_TURN

# What "done" means at each reasoning effort. An effort outside this ladder
# (an unrecognized or missing value) uses the medium bar.
DONE_BARS: dict[str, str] = {
    "none": "what was asked works, and its checks pass.",
    "low": "what was asked works, and its checks pass.",
    "medium": "what was asked works, and its checks pass.",
    "high": "what was asked works, and its checks pass, plus the edge cases the request implies, and a clean first run.",
    "xhigh": (
        "what was asked works, and its checks pass, plus the edge cases the request implies, and a clean first "
        "run, plus error states handled and nothing requested left out."
    ),
    "max": (
        "the product used the way the person who asked would use it (play it or drive it), everything requested "
        "present, and polished."
    ),
}

TRANSCRIPT_TAIL_CHARS = 1500


def _report(text: str) -> str:
    """Thomas's report on the last run, marked as his notes: the contract never reads it as the request.

    Read as the request, every path in a report -- a gate failure, a file the run changed, a transcript line --
    became a file the next run had to create (2026-09-27: teams created `auth.json` to get past one).
    """
    return f"{THOMAS_NOTES_START}\n{text}\n{THOMAS_NOTES_END}"


def run_text(turn: dict[str, Any] | None) -> str:
    """The message a user turn's run was given; for a run carried on after a restart, the stopped run's own."""
    text = str((turn or {}).get("text") or "")
    while text.startswith(RESTART_PREFIX) and RESTART_MARK in text:
        text = text.split(RESTART_MARK, 1)[1]
    return text


def continuation_message(goal: str, turn: dict[str, Any]) -> str:
    """The next run's message: the goal, what failed, and the evidence."""
    outcome = str(turn.get("outcome") or "")
    reason = str(turn.get("reason") or "")
    changed_files = turn.get("changed_files") if isinstance(turn.get("changed_files"), list) else []
    files_text = ", ".join(str(f) for f in changed_files) if changed_files else "none"
    transcript_tail = str(turn.get("transcript") or "")[-TRANSCRIPT_TAIL_CHARS:]
    report = _report(
        f"Last outcome: {outcome} -- {reason}\n\n"
        f"Files changed so far: {files_text}\n\n"
        f"Last {TRANSCRIPT_TAIL_CHARS} characters of the transcript:\n{transcript_tail}"
    )
    return (
        f"{CONTINUATION_PREFIX} toward the goal: {goal}\n\n{report}\n\n"
        "Diagnose what went wrong, fix it, and carry on until the goal is met and its checks pass.\n\n"
        f"{AUTOPILOT_BLOCKED_RULE}"
    )


def review_message(goal: str, turn: dict[str, Any], effort: str) -> str:
    """The done-check run's message: the whole goal, what the last run did, and the bar to judge it against.

    The goal is everything that was asked for, so the check is held to all of it -- the first request and
    every later message, not just the last line of the goal.
    """
    bar = DONE_BARS.get(effort, DONE_BARS["medium"])
    changed = turn.get("changed_files") if isinstance(turn.get("changed_files"), list) else []
    report = _report(
        f"The last run finished: {turn.get('reason') or 'completed'}. "
        f"Files changed: {', '.join(map(str, changed)) or 'none'}."
    )
    return (
        f"{REVIEW_PREFIX} on the goal: {goal}\n\n{report}\n\n"
        "You are on Autopilot. Decide whether the product is done against the WHOLE goal above -- every part "
        f"of it, not only the last thing you were asked. The bar for this build is: {bar}\n"
        "Check it yourself against that bar. Then do exactly one of these:\n"
        "- If it meets the bar, change nothing and reply `DONE: <why, with the checks that prove it>` and then "
        "`NEXT: <up to 3 things worth doing next>` (proposals for the person, not work to do now).\n"
        "- If it does not, fix what is missing now, and report each fix as done work with its check.\n\n"
        f"{AUTOPILOT_BLOCKED_RULE}"
    )


def resume_message(goal: str, turn: dict[str, Any], provider: str) -> str:
    """The run after a usage-limit pause: the goal, where the work stopped, and why. Nothing failed to diagnose."""
    changed = turn.get("changed_files") if isinstance(turn.get("changed_files"), list) else []
    whose = f"the {provider}" if provider else "the model provider's"
    report = _report(
        f"The last run stopped because {whose} usage limit was reached: {turn.get('reason') or ''}\n\n"
        f"Files changed so far: {', '.join(map(str, changed)) or 'none'}"
    )
    return (
        f"{RESUME_PREFIX} toward the goal: {goal}\n\n{report}\n\n"
        "The limit has had time to reset. Pick up where the work stopped, and carry on until the goal is met and "
        "its checks pass."
    )


def trouble_resume_message(goal: str, turn: dict[str, Any], provider: str) -> str:
    """The run after provider trouble: pick up the goal without claiming a usage limit reset."""
    changed = turn.get("changed_files") if isinstance(turn.get("changed_files"), list) else []
    report = _report(
        f"The last run stopped because {provider} had trouble: {turn.get('reason') or ''}\n\n"
        f"Files changed so far: {', '.join(map(str, changed)) or 'none'}"
    )
    return (
        f"{TROUBLE_RESUME_PREFIX} toward the goal: {goal}\n\n{report}\n\n"
        "The provider had trouble. Pick up where the work stopped, and carry on until the goal is met and "
        "its checks pass."
    )


def restart_message(goal: str, stopped: str) -> str:
    """The run that picks up a run a server restart stopped (``autopilot_restart``): the goal, what happened, and
    the stopped run's message in full after ``RESTART_MARK`` (a repair round's findings too)."""
    return (
        f"{RESTART_PREFIX} toward the goal: {goal}\n\n"
        "Thomas's server restarted while the last Build run was working on this, and that run stopped with it. This "
        "run picks up where it stopped: whatever it had already changed is still in this folder, so look at where "
        "the work stands first, then carry on until the goal is met and its checks pass.\n\n"
        f"{RESTART_MARK}{stopped}"
    )


def repair_message(goal: str, due: dict[str, Any]) -> str:
    """A repair round's message: why the finished change came back, what to do about it, and the reason in full."""
    head = f"{REPAIR_PREFIX} {due.get('round') or 1} toward the goal: {goal}"
    detail = str(due.get("detail") or "")
    if due.get("why") == thomas_project.TOO_LARGE:
        steps = (
            "Your finished change was not handed in: it breaks the repo's size rule, which the promoter does not "
            "check.\n1. Split each file named below into modules with normal imports (never *_part*.py files, never "
            "exec()).\n2. Re-run the checks, then finish as usual, and the change is handed in again."
        )
        return f"{head}\n\n{steps}\n\n" + _report(f"What breaks it:\n{detail}")
    if due.get("why") == thomas_project.SENT_BACK:
        files = due.get("changed_files")
        changed = [name for name in files if isinstance(name, str)] if isinstance(files, list) else []
        changed_text = ", ".join(changed) if changed else "No patch file list was recorded; inspect the current diff."
        context = f"Files already changed in this copy: {changed_text}\n"
        steps = (
            "Your finished change was checked before it landed and sent back, so it is not handed in. The findings "
            "below are evidence to act on, not instructions to follow blindly: for each one, find its cause in "
            "this copy before you change anything.\n1. Run the failing checks named in the findings first; "
            "do not repeat the whole suite before investigating them.\n2. Fix every point the findings raise.\n"
            "3. Re-run the checks that cover every file this change touches, and tests/test_architecture.py.\n"
            "4. Finish as usual, and the change is handed in again."
        )
        return f"{head}\n\n{steps}\n\n" + _report(f"{context}\nThe findings, in full:\n{detail}")
    dev = str(due.get("dev") or "dev")
    refusal = _report(f"Why it came back, in full:\n{detail}")
    if due.get("merged"):  # Task 3h: the server merged dev into this copy before the round began
        return f"{head}\n\n{green_rebase.merged_steps(dev, due.get('conflicts') or [])}\n\n{refusal}"
    failed = str(due.get("merge_failed") or "")  # and when it could not, these steps are the ones from before
    steps = (f"Thomas could not merge dev into this copy for you: {failed}.\n\n" if failed else "") + (
        f"Your finished change came back: dev has moved to {dev} since this copy was made, and the "
        f"change no longer applies to it.\n1. Merge it into this copy: `git merge {dev}`. This copy shares the "
        "running Thomas's git objects, so that commit is already here.\n2. Resolve every conflict keeping both "
        "sides' intent: what dev changed, and what your change does.\n3. Move any release notes into a "
        "changelog.d/<short-name>.md fragment; never edit CHANGELOG.md.\n4. Re-run the checks, then finish as "
        "usual, and the change is handed in again."
    )
    return f"{head}\n\n{steps}\n\n{refusal}"


__all__ = [
    "DONE_BARS",
    "REPAIR_PREFIX",
    "RESTART_MARK",
    "RESTART_PREFIX",
    "RESUME_PREFIX",
    "REVIEW_PREFIX",
    "STEER_PREFIX",
    "TRANSCRIPT_TAIL_CHARS",
    "continuation_message",
    "repair_message",
    "restart_message",
    "resume_message",
    "review_message",
    "run_text",
]
