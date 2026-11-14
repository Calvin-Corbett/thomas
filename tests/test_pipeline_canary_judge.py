"""The canary judges a new commit's selection against the good one, measured the same way (2026-10-27)."""

from __future__ import annotations

import pytest
from scripts.pipeline_canary.judge import judge
from scripts.pipeline_canary.measure import Measurement


def ran(seconds: float, files: int, left_out: int = 0) -> Measurement:
    return Measurement("c", seconds, files, left_out)


def test_the_fix_after_e51b2c7f_is_fine_against_the_commit_before_it() -> None:
    assert judge(ran(28.5, 35), ran(39.9, 49)) == []


def test_a_selection_that_did_not_finish_is_an_alarm() -> None:
    assert judge(ran(28.5, 35), Measurement("c", None, error="it did not finish: over 600 s")) == [
        "it did not finish: over 600 s"
    ]


@pytest.mark.parametrize(
    ("good", "new", "alarm"),
    [
        (10.0, 49.0, False),
        (10.0, 50.0, True),
        (1.0, 9.0, False),  # under the 2-second floor's five times: tiny times are noise
        (1.0, 10.0, True),
    ],
)
def test_five_times_as_long_is_an_alarm(good: float, new: float, alarm: bool) -> None:
    reasons = judge(ran(good, 40), ran(new, 40))
    assert bool(reasons) is alarm
    if alarm:
        assert reasons == [f"it took {new:.1f} s, at least 5 times the {good:.1f} s before it"]


def test_more_than_the_cap_is_an_alarm() -> None:
    assert judge(ran(10, 40), ran(10, 300, 61)) == ["it chose 361 test files, more than the 360 a check runs"]


def test_with_no_good_measurement_there_is_nothing_to_judge_against() -> None:
    assert judge(Measurement("c", None, error="it failed: x"), ran(500, 40)) == []
