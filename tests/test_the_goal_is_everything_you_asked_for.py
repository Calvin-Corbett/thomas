"""On Autopilot, a follow-up adds to the goal -- it never becomes the whole goal by itself.

You said: "your done check takes my latest message as the whole goal and forgets what I asked for first."
Measured 2026-09-25: a Thomas project the server restarted was sent "Carry on from where you stopped..."
and from that turn on the done check judged the work against "carry on" instead of the cleanup you had
asked for, because the goal was one turn -- the last user turn Autopilot had not written itself.

The proof you asked for is `test_a_carry_on_then_an_also_holds_the_work_to_both`: ask for A, say "carry on",
say "also B", and the done check's own message has to hold the run to A and B.

Every conversation here is built through the real store and catalog (`_bind_conv`, reused from
`tests/test_autopilot_decides_when_it_is_done.py`), never a hand-built `{"settings": ...}` dict: that
shortcut once shipped a dead Autopilot feature that never fired in the app at all.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_autopilot_decides_when_it_is_done import _bind_conv, _decide, _finished_turn
from tests.test_autopilot_keeps_going import _partial_turn
from thomas.server import thomas_project
from thomas.server.routes import autopilot_goal
from thomas.server.routes import evolve_agent_autopilot as ap

FIRST = "make me a pokemon game"  # what `_bind_conv` records as your first turn
CARRY_ON = "Carry on from where you stopped. Do not restart from scratch."
ALSO = "also make the button blue"
CHECK = f"{ap.REVIEW_PREFIX} on the goal: {FIRST}"  # a done check begun before 2026-11-13


def _goal_of(message: str) -> str:
    """The goal an Autopilot message carries: everything after "the goal: " up to the next blank line."""
    return message.split("the goal: ", 1)[1].split("\n\n", 1)[0]


# ── the proof: A, then "carry on", then "also B" ──


def test_a_carry_on_then_an_also_holds_the_work_to_both(tmp_path: Path) -> None:
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        reasoning_effort="max",
        # A done check already running (none starts since 2026-11-13) that changed files gets another one.
        agent_turn_kwargs_list=[
            _partial_turn(),
            _partial_turn(),
            _finished_turn(["index.html"]),
            _finished_turn(["a"]),
        ],
        extra_user_texts=[CARRY_ON, ALSO, CHECK],
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "review", d
    assert d.message.startswith(ap.REVIEW_PREFIX)
    assert FIRST in d.message, "the first request is still the goal"
    assert ALSO in d.message, "and so is what the later message added"
    assert CARRY_ON in d.message, "including the message that asked for neither"
    assert _goal_of(d.message).startswith(autopilot_goal.GOAL_HEAD), "the goal says a later message wins"
    assert d.message.index(FIRST) < d.message.index(ALSO), "oldest first, so the later one reads as the later one"
    assert "WHOLE goal above" in d.message, "the done check is told to judge all of it"


def test_the_goal_is_no_longer_the_latest_message_alone(tmp_path: Path) -> None:
    """The regression itself: "carry on" as the whole goal, with the first request gone from the message."""
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[_partial_turn(), _finished_turn(["index.html"]), _finished_turn(["a"])],
        extra_user_texts=[CARRY_ON, CHECK],
    )

    goal_read = _goal_of(_decide(catalog_root, project_root, cid).message)

    assert goal_read != CARRY_ON, "the latest message is not the goal"
    assert FIRST in goal_read


def test_a_failed_run_carries_the_whole_goal_into_its_next_round(tmp_path: Path) -> None:
    """Not only the done check: the continuation that hands the next run the failure's evidence, too."""
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), _partial_turn()],
        extra_user_texts=[ALSO],
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "continue" and d.message.startswith(ap.CONTINUATION_PREFIX)
    assert FIRST in d.message and ALSO in d.message


# ── what the goal is made of ──


def test_one_request_is_still_the_goal_word_for_word() -> None:
    """A conversation you only asked once reads exactly as it did before there was a second message."""
    assert autopilot_goal.goal_text([{"role": "user", "text": FIRST}]) == FIRST
    assert autopilot_goal.goal_text([]) == ""


def test_autopilots_own_rounds_are_never_part_of_the_goal() -> None:
    """Continuations, done checks, resumes and repair rounds are Thomas's own turns, not instructions."""
    turns = [
        {"role": "user", "text": FIRST},
        {"role": "user", "text": f"{ap.CONTINUATION_PREFIX} toward the goal: {FIRST}\n\nLast outcome: failed"},
        {"role": "user", "text": f"{ap.REVIEW_PREFIX} on the goal: {FIRST}"},
        {"role": "user", "text": f"{ap.RESUME_PREFIX} toward the goal: {FIRST}"},
        {"role": "user", "text": f"{ap.REPAIR_PREFIX} 1 of 3 toward the goal: {FIRST}"},
        {"role": "agent", "text": "an agent turn is not an instruction either"},
    ]

    assert autopilot_goal.instructions(turns) == [FIRST]
    assert autopilot_goal.goal_text(turns) == FIRST, "one instruction, so no list and no nesting"


def test_a_steer_you_sent_from_chat_joins_the_goal_and_a_quoted_one_does_not() -> None:
    """Your steer rides inside a round Thomas wrote, in its second paragraph -- so it outlives that round.

    A transcript tail quoting an earlier steer must not be read as a new one, or every later round would
    add the same instruction again.
    """
    head = f"{ap.CONTINUATION_PREFIX} toward the goal: {FIRST}"
    steered = thomas_project.steering_message(["use green, not blue"], f"{head}\n\nLast outcome: failed")
    quoted = f"{head}\n\nLast outcome: failed -- the log said Steering update: use red"
    two = thomas_project.steering_message(["add a pause key", "keep the music"], f"{head}\n\nLast outcome: failed")

    asked = autopilot_goal.instructions([{"role": "user", "text": t} for t in (FIRST, steered, quoted, two)])

    assert asked == [FIRST, "use green, not blue", "add a pause key", "keep the music"]


def test_the_round_autopilot_starts_for_your_steering_carries_that_steer_into_the_goal() -> None:
    """`_start_steered_round` builds a round of its own for steering that arrived with no run to take it.

    That round starts with STEER_PREFIX, so it is one of Thomas's own turns -- but skipping it whole would
    drop the steering it was started for, which is the one instruction from you inside it.
    """
    rest = "Apply it first, then carry on until the goal is met and its checks pass."
    started = thomas_project.steering_message(
        ["make the button blue"], f"{ap.STEER_PREFIX} toward the goal: {FIRST}\n\n{rest}"
    )
    turns = [{"role": "user", "text": FIRST}, {"role": "user", "text": started}]

    assert autopilot_goal.instructions(turns) == [FIRST, "make the button blue"], "the steer, once, and no more"
    assert ap.STEER_PREFIX not in autopilot_goal.goal_text(turns), "the round's own message never nests in the goal"


def test_the_goal_stays_one_paragraph_so_a_steer_still_splices_after_it() -> None:
    """`thomas_project.steering_message` splits a run's message on its first blank line: a goal carrying a
    blank line of its own would swallow that splice point and the steer would land inside the goal."""
    spread = "clean up the repo\n\nleave the tests alone"
    turns = [{"role": "user", "text": spread}, {"role": "user", "text": ALSO}]

    text = autopilot_goal.goal_text(turns)

    assert "\n\n" not in text
    assert "1. clean up the repo\n   leave the tests alone" in text
    assert text.endswith(f"2. {ALSO}")


def test_the_fuse_still_counts_only_autopilots_own_rounds() -> None:
    """The steer read is shared with the 12-round fuse; a quoted steer must not reset it (round 2, N2)."""
    head = f"{ap.CONTINUATION_PREFIX} toward the goal: g"
    quoted = f"{head}\n\nLast outcome: failed -- the log said Steering update: use green"
    steered = thomas_project.steering_message(["use green"], f"{head}\n\nLast outcome: failed")

    ended = {
        "role": "agent",
        "outcome": "failed",
        "reason": "run ended",
        "transcript": '{"fc":"say","text":"Checking the game","source":"model"}',
    }
    assert (
        ap._continuation_count(
            [
                {"role": "user", "text": "g"},
                {"role": "user", "text": quoted},
                ended,
                {"role": "user", "text": quoted},
                ended,
            ]
        )
        == 2
    )
    assert (
        ap._continuation_count(
            [
                {"role": "user", "text": "g"},
                {"role": "user", "text": steered},
                ended,
                {"role": "user", "text": quoted},
                ended,
            ]
        )
        == 1
    )
