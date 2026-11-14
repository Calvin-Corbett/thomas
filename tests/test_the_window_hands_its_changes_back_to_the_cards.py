"""The window's loop hands its changes back to the cards whenever it cannot be relied on (2026-10-14 review, D2, D3).

With no one outside Thomas holding a change aside, the window's lane and the card loop decide in turn, under the card
loop's own lock. The rig, its stand-ins and fixtures are the loop's own (tests/test_the_window_loop_runs_beside_the_cards.py).
"""

from __future__ import annotations

import shutil

import pytest
from scripts.cage import window_control as wc
from scripts.cage import window_loop as wl

from tests.test_the_window_loop_runs_beside_the_cards import SID, Rig, rig  # noqa: F401 - fixtures


def test_the_lane_takes_its_hand_ins_under_the_card_loops_lock_and_only_for_an_open_window(rig: Rig) -> None:
    rig.loop.tick()
    wc.request(rig.home, "open", minutes=60)
    rig.loop.tick()
    rig.link.why_not = "the checker is not running (no heartbeat)"
    rig.loop.tick()

    assert rig.lane.took == [(False, True, True), (True, True, True), (True, False, True)]
    assert not rig.card.taking.locked()


class _Passes:
    """A stop event that lets *count* passes run."""

    def __init__(self, count: int) -> None:
        self.left = count

    def wait(self, _interval: float) -> bool:
        self.left -= 1
        return self.left < 0


def test_a_failed_pass_hands_the_windows_changes_to_the_cards_until_a_pass_works(rig: Rig) -> None:
    # 2026-10-14 review, D2: an ImportError was not one of the loop's faults, so it ended the thread with the window's
    # hand-ins still kept off the cards and the status looking alive.
    step = rig.lane.step

    def broken(*_args: object, **_kwargs: object) -> None:
        raise ImportError("a lazy import failed")

    rig.lane.step = broken  # type: ignore[method-assign]
    rig.loop.run(_Passes(1), interval_s=0)  # type: ignore[arg-type]
    assert rig.loop.healthy is False and rig.loop.card_skip() == frozenset()
    rig.lane.step = step  # type: ignore[method-assign]
    rig.loop.tick()
    assert rig.loop.card_skip() == frozenset({SID})


def test_when_the_loop_ends_the_cards_take_every_change_and_the_window_closes(rig: Rig) -> None:
    rig.card.skip = rig.loop.card_skip
    rig.loop.run(_Passes(2), interval_s=0)  # type: ignore[arg-type]
    assert rig.card.skip() == frozenset() and rig.lane.closed and rig.window.opened is None


@pytest.mark.parametrize("trouble", ["off", "checker", "record"])
def test_an_off_switch_or_no_checker_or_record_returns_changes_to_their_cards(rig: Rig, trouble: str) -> None:
    # 2026-10-14 review, D3 (spec 8.8: an off switch "returns every change to cards"): the window's hand-ins once
    # waited for a window that could not open, with no card, for as long as the trouble lasted.
    if trouble == "off":
        rig.home.mkdir(parents=True, exist_ok=True)
        (rig.home / wl.OFF).write_text("off", encoding="utf-8")
    elif trouble == "checker":
        rig.link.why_not = "the checker is not running (no heartbeat)"
    else:
        shutil.rmtree(rig.record.root)
    assert rig.loop.card_skip() == frozenset()


def test_no_landing_is_allowed_while_the_checker_cannot_be_relied_on(rig: Rig) -> None:
    rig.link.why_not = "the checker has not shown that it is fenced off the network"
    rig.loop.tick()
    assert rig.lane.allowed[-1] is False
    rig.link.why_not = ""
    rig.loop.tick()
    assert rig.lane.allowed[-1] is True
