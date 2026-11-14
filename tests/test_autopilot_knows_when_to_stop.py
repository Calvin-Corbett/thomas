"""A Thomas project that stops making progress pauses and asks you; one still making progress is never cut off.

You said "he needs a good this enough to stop": one project failed its check 48 times in a row, another's check came
back unavailable 35 times, a dozen Builds ran 30-84 hours. Real here: the conversation store, the hold store, the park
list, decide, the phase and the restart's carry-on. Stubbed: only what would start a real run or a real check.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_store
from thomas.server import autopilot_enough as enough
from thomas.server import autopilot_park, autopilot_restart, hand_in_hold, hand_in_hold_store, precard, thomas_project
from thomas.server.routes import evolve_agent_autopilot as ap

CID = "enough-1"
ASK = {"role": "user", "text": "make the button blue", "ts": "2026-11-01T00:00:00+00:00"}
FINISHED = {"role": "agent", "ok": True, "outcome": "completed", "changed_files": ["a.py"], "reason": "done"}


def _failing(n: int) -> str:
    return "\n".join(f"FAILED tests/test_x.py::t{i}" for i in range(n))


def _rounds(*counts: int) -> list[dict[str, Any]]:
    at = "2026-11-02T00:00:{:02d}+00:00"
    return [
        {"round": i + 1, "why": thomas_project.SENT_BACK, "detail": _failing(n), "at": at.format(i)}
        for i, n in enumerate(counts)
    ]


def _write(root: Path, turns: list[dict[str, Any]], **project: Any) -> dict[str, Any]:
    conversation = {"id": CID, "turns": turns, "thomas_project": {"execution_id": "green-1", **project}}
    forge_code_store.write_conversation(root, conversation)
    return conversation


def _load(root: Path) -> dict[str, Any]:
    return forge_code_store.load_conversation(root, CID) or {}


def _autopilot(conversation: dict[str, Any]) -> dict[str, Any]:
    return {**conversation, "settings": {"requested": {"autonomy_level": ap.AUTOPILOT}}}


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    root, catalog = tmp_path / "green", tmp_path / "catalog"
    root.mkdir()
    catalog.mkdir()
    return root, catalog


def test_findings_are_counted_by_failing_test_and_by_problem_count() -> None:
    assert enough.failing_count(_failing(3) + "\nFAILED tests/test_x.py::t0") == 3
    assert enough.failing_count("Heading:\n- tests/a.py::t\n- tests/b.py::t\n- and 4 more") == 6
    assert enough.failing_count("Checked against dev abc: 7 problem(s), so it went back to its team.") == 7
    assert enough.failing_count("the tests could not be run at all") is None
    assert enough.no_new_lowest([3, 3, 2, 2, 2]) == (2, 2)
    assert enough.no_new_lowest([None, None]) == (2, None)


def test_five_sent_back_rounds_with_no_new_lowest_pause_instead_of_repairing(roots: tuple[Path, Path]) -> None:
    root, catalog = roots
    _write(root, [ASK, FINISHED], repairs=_rounds(4, 4, 5, 4, 4))  # 4 is the lowest; 4 rounds since, now a 5th
    assert enough.repairs_stalled(root, catalog, CID, thomas_project.SENT_BACK, _failing(4))
    words = enough.standing(_load(root))
    assert "sent back to its team 6 times" in words and "fewest so far (4; this time 4)" in words
    assert autopilot_park.parked(catalog, CID)["enough"] == "repairs"  # the park loop starts your reply


def test_a_new_lowest_starts_the_count_again(roots: tuple[Path, Path]) -> None:
    root, catalog = roots
    _write(root, [ASK, FINISHED], repairs=_rounds(9, 9, 9, 9, 8))  # 8 is a new lowest: progress
    assert not enough.repairs_stalled(root, catalog, CID, thomas_project.SENT_BACK, _failing(8))
    assert not enough.repairs_stalled(root, catalog, CID, thomas_project.SENT_BACK, _failing(7))
    assert enough.standing(_load(root)) == ""


def test_rounds_before_your_last_message_do_not_count(roots: tuple[Path, Path]) -> None:
    root, catalog = roots
    later = {"role": "user", "text": "try another way", "ts": "2026-11-03T00:00:00+00:00"}
    _write(root, [ASK, FINISHED, later, FINISHED], repairs=_rounds(4, 4, 4, 4, 4, 4))
    assert not enough.repairs_stalled(root, catalog, CID, thomas_project.SENT_BACK, _failing(4))


def test_a_failed_check_that_stalled_starts_no_repair_round(roots: tuple[Path, Path], monkeypatch) -> None:
    root, catalog = roots
    started: list[str] = []

    async def off_the_loop(*_args: Any, **_kwargs: Any) -> None:
        raise precard.ChangeFailedCheck(_failing(4))

    async def start_repair(*_args: Any, **kwargs: Any) -> None:
        started.append(kwargs["why"])

    from thomas.server import autopilot_hold_tick, self_change_status

    monkeypatch.setattr(self_change_status, "claim", lambda cid: True)
    monkeypatch.setattr(self_change_status, "release", lambda cid: None)
    monkeypatch.setattr(precard.workers, "off_the_loop", off_the_loop)
    monkeypatch.setattr(hand_in_hold, "still_current", lambda *a, **k: True)
    monkeypatch.setattr(hand_in_hold, "drop", lambda *a, **k: True)
    monkeypatch.setattr(autopilot_hold_tick, "hold_if_unfinished", lambda *a, **k: None)
    monkeypatch.setattr(ap, "start_repair", start_repair)
    stalled = [True, False]
    monkeypatch.setattr(enough, "repairs_stalled", lambda *a: stalled.pop(0))
    for _ in range(2):
        asyncio.run(ap._settle_thomas_project(root, catalog, CID, app={}, gen=[1, "", "x"]))
    assert started == [thomas_project.SENT_BACK], "the stalled one paused; the next, still progressing, went back"


def _held(catalog: Path, tries: int) -> dict[str, Any]:
    row = {"cid": CID, "project_root": "", "gen": [2, "", "h"], "state": "checking", "tries": tries, "strikes": 0}
    hand_in_hold_store.write(catalog, [row])
    return row


def test_four_unavailable_checks_in_a_row_pause_instead_of_another_try(roots: tuple[Path, Path], monkeypatch) -> None:
    root, catalog = roots
    _write(root, [ASK, FINISHED])
    monkeypatch.setattr(hand_in_hold, "still_current", lambda *a, **k: True)
    line = "Not checked before this card: there was no room to check it."
    for tries in (1, 2, 3):
        _held(catalog, tries)
        held = hand_in_hold.hold_unavailable(root, catalog, CID, precard.CheckUnavailable(line), gen=[2, "", "h"])
        assert held is not None and held["state"] == "held"
    _held(catalog, 4)
    assert hand_in_hold.hold_unavailable(root, catalog, CID, precard.CheckUnavailable(line), gen=[2, "", "h"]) is None
    assert hand_in_hold.row(catalog, CID) is None, "no further try is scheduled"
    assert line in enough.standing(_load(root))


def test_the_same_try_counts_once_and_a_verdict_starts_the_count_again(roots: tuple[Path, Path]) -> None:
    root, catalog = roots
    _write(root, [ASK, FINISHED])
    for key in ([1], [1], [2], [3]):  # the second [1] is the same try written again: not counted
        assert not enough.unavailable_stalled(root, catalog, CID, "no room", key=key)
    conversation = _load(root)
    conversation["thomas_project"]["repairs"] = _rounds(3)  # a verdict sent it back in between
    forge_code_store.write_conversation(root, conversation)
    for key in ([4], [5], [6]):
        assert not enough.unavailable_stalled(root, catalog, CID, "no room", key=key)
    assert enough.unavailable_stalled(root, catalog, CID, "no room", key=[7])


def _done_checks(count: int, *, changed: bool = True) -> list[dict[str, Any]]:
    check = {"role": "user", "text": f"{ap.REVIEW_PREFIX} at the medium bar"}
    return [t for _ in range(count) for t in (check, {**FINISHED, "changed_files": ["a.py"] if changed else []})]


def test_six_done_checks_that_each_changed_files_pause_autopilot() -> None:
    six = _autopilot({"id": CID, "turns": [ASK, FINISHED, *_done_checks(6)]})
    five = _autopilot({"id": CID, "turns": [ASK, FINISHED, *_done_checks(5)]})
    assert ap.decide(six).action == "enough" and "6 done checks" in ap.decide(six).reason
    assert ap.decide(five).action == "review"
    reset = _autopilot({"id": CID, "turns": [ASK, *_done_checks(3), {**ASK, "text": "also red"}, *_done_checks(5)]})
    assert ap.decide(reset).action == "review", "your message starts the count again"
    below = {**six, "settings": {"requested": {"autonomy_level": 3}}}
    assert ap.decide(below).action == "off", "the done-check rule is Autopilot's only"


def test_six_tweaking_done_checks_stamp_the_pause_once(roots: tuple[Path, Path], monkeypatch) -> None:
    root, catalog = roots
    _write(root, [ASK, FINISHED, *_done_checks(6)])
    joined = _autopilot(_load(root))
    monkeypatch.setattr(ap, "_load_joined_conversation", lambda *a: joined)
    decision = asyncio.run(ap.continue_after_turn({}, root, catalog, CID))
    assert decision.action == "enough" and enough.standing(_load(root)) == decision.reason
    assert autopilot_park.parked(catalog, CID) is not None


def test_a_pause_answers_enough_shows_paused_and_lifts_on_your_next_message(roots: tuple[Path, Path]) -> None:
    root, catalog = roots
    _write(root, [ASK, FINISHED])
    assert enough.stamp(root, catalog, CID, why="repairs", words="Paused for you: test.")
    conversation = _load(root)
    assert ap.decide(conversation) == ap.Decision("enough", "Paused for you: test.")  # at every autonomy level
    assert not ap._thomas_project_should_settle(ap.decide(conversation), conversation), "not handed in again"
    phase = thomas_project._stored_phase(root, catalog, CID, conversation=conversation, metadata={})
    assert phase == ("paused", "Paused for you: test."), "paused, never ended: the copy is kept"
    autopilot_round = {"role": "user", "text": f"{ap.REVIEW_PREFIX} at the medium bar"}
    assert enough.standing({**conversation, "turns": [*conversation["turns"], autopilot_round]})
    steered = {"role": "user", "text": f"{ap.STEER_PREFIX} toward the goal\n\nSteering update: go on\n\nrest"}
    assert enough.standing({**conversation, "turns": [*conversation["turns"], steered]}) == ""
    mine = {"role": "user", "text": "carry on"}
    assert ap.decide({**conversation, "turns": [*conversation["turns"], mine]}).action != "enough"


def test_a_restart_does_not_carry_a_paused_project_on(roots: tuple[Path, Path], monkeypatch) -> None:
    root, catalog = roots
    conversation = _write(root, [ASK, FINISHED], enough={"why": "repairs", "words": "Paused for you: x.", "turns": 2})
    monkeypatch.setattr(autopilot_restart, "_written_since", lambda *a: False)
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda cid: ([], []))
    monkeypatch.setattr(thomas_project, "_read_live", lambda *a: conversation)
    item = autopilot_restart.Interrupted(CID, root, ASK, 0.0, True, "", "run-1")
    assert asyncio.run(autopilot_restart._carry_on({}, catalog, item, observed_at=1.0)) == (
        "left",
        "Paused for you: x.",
    )


def test_your_reply_from_chat_is_started_by_the_park_loop(roots: tuple[Path, Path], monkeypatch) -> None:
    root, catalog = roots
    _write(root, [ASK, FINISHED])
    enough.stamp(root, catalog, CID, why="unavailable", words="Paused for you: y.")
    steers = ["go on"]
    started: list[str] = []

    async def steered(app: Any, conversation: dict[str, Any], cid: str, catalog_root: Path) -> None:
        started.append(cid)
        steers.clear()

    monkeypatch.setattr(thomas_project, "held_steers", lambda cid: list(steers))
    monkeypatch.setattr(ap, "_start_steered_round", steered)
    assert asyncio.run(autopilot_park.resume_due({}, catalog, now=0.0)) == [CID]
    assert started == [CID]
