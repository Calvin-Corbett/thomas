"""A held change waits longer after each try it could not finish (2026-10-27).

It was tried every 15 minutes, each try a full check: on 2026-10-27 a change that selected 1,961 test files ran
past its hour limit nine times in a day. Now it waits 15 minutes twice, then twice as long each time, at most two
hours.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import hand_in_hold_support as support
from thomas.server import capacity_ledger, hand_in_hold

NOW = 1_800_000_000.0


@pytest.mark.parametrize(
    ("tries", "minutes"), [(0, 15), (1, 15), (2, 15), (3, 30), (4, 60), (5, 120), (6, 120), (40, 120)]
)
def test_the_wait_doubles_after_the_second_try_up_to_two_hours(tries: int, minutes: int) -> None:
    assert hand_in_hold.retry_after(tries) == minutes * 60


def test_a_fourth_try_that_could_not_run_waits_an_hour(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(hand_in_hold, "clock", lambda: NOW)
    project = support.make_project(tmp_path, monkeypatch)
    booked = support.book(project)
    fourth = {**booked, "tries": 4}
    assert hand_in_hold.change(project[1], project[2], booked["gen"], fourth, expected=booked)
    held = hand_in_hold.hold(project[0], project[1], project[2], "check", "it ran out of its 60-minute limit")
    assert held is not None and held["state"] == "held" and held["next_at"] == NOW + 3600
