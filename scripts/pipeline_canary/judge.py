"""Judge a new commit's selection against the good one, measured the same way on the same machine.

Against measured normal, not a guessed clock: on 2026-10-27 the same selection took 9 to 13 s on a quiet machine and
28 to 40 s on a busy one, so a fixed limit either fired on load or missed e51b2c7f (still running at 300 s).
"""

from __future__ import annotations

from scripts.pipeline_canary.measure import Measurement

RATIO = 5.0  # this many times the good commit's seconds is an alarm
FLOOR_S = 2.0  # the good commit's seconds are counted as at least this, so tiny times are not noise
CAP = 360  # the most test files a check runs (thomas/server/proof/selection.py CAP)


def judge(good: Measurement, new: Measurement) -> list[str]:
    """Why *new* is an alarm against *good*, one reason a line; empty when it is fine or nothing judges it."""
    if good.seconds is None:
        return []  # no good measurement to compare with: the caller sets a new baseline instead
    if new.seconds is None:
        return [new.error or "it gave no measurement"]
    reasons = []
    if new.seconds >= RATIO * max(good.seconds, FLOOR_S):
        reasons.append(f"it took {new.seconds:.1f} s, at least {RATIO:g} times the {good.seconds:.1f} s before it")
    chosen = new.files + new.left_out
    if chosen > CAP:
        reasons.append(f"it chose {chosen} test files, more than the {CAP} a check runs")
    return reasons


__all__ = ["CAP", "FLOOR_S", "RATIO", "judge"]
