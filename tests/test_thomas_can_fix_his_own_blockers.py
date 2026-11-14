"""The level where a blocker is work, not a reason to stop.

Owner direction: "if there is a blocker, fix the blocker... there should be
never anything that stops you." The control model calls this L5 / auto agent
mode. It did not exist: ``_SPECS`` stopped at 4 and ``clamp_autonomy_level``
capped every request at 4, so the top of the ladder was L4 Full Autonomy, whose
own directive ends "Only stop if something is truly impossible or unsafe."

That last clause is the whole difference. At L4 a missing dependency, a failing
gate or a refused tool is a legitimate place to stop and report. At L5 it is the
next task: fix it, then carry on with what you were doing.

L4 keeps its name and its number, because `parse_autonomy_level("full autonomy")`
is 4 everywhere and callers rely on it. L5 is Autopilot.
"""

from __future__ import annotations

from thomas.core.autonomy import (
    DEFAULT_AUTONOMY_LEVEL,
    autonomy_spec,
    clamp_autonomy_level,
    parse_autonomy_level,
)


def test_there_is_a_level_above_full_autonomy() -> None:
    spec = autonomy_spec(5)
    assert spec.level == 5, "L5 does not exist, so nothing can be put into it"


def test_asking_for_level_five_is_not_silently_downgraded() -> None:
    """The cap was the reason the level could not be reached even once it existed."""
    assert clamp_autonomy_level(5) == 5


def test_anything_above_five_still_clamps() -> None:
    assert clamp_autonomy_level(6) == 5
    assert clamp_autonomy_level(99) == 5


def test_level_five_is_told_to_fix_the_blocker_rather_than_stop() -> None:
    """The behaviour that distinguishes it, in the words that reach the model."""
    directive = autonomy_spec(5).system_directive.casefold()
    assert "blocker" in directive
    assert "fix" in directive


def test_level_four_still_stops_and_level_five_does_not() -> None:
    """Pinned as a pair. If these ever read the same, the new level is cosmetic."""
    four = autonomy_spec(4).system_directive.casefold()
    five = autonomy_spec(5).system_directive.casefold()
    assert "only stop if" in four
    assert "only stop if" not in five


def test_full_autonomy_still_means_four() -> None:
    """Existing callers resolve this label; L5 must not steal it."""
    assert parse_autonomy_level("full autonomy") == 4
    assert parse_autonomy_level("full_autonomy") == 4


def test_autopilot_resolves_by_its_own_name() -> None:
    assert parse_autonomy_level("autopilot") == 5


def test_the_default_is_still_ask_first() -> None:
    """Design law: the user opts UP into hands-off autonomy, never by default."""
    assert DEFAULT_AUTONOMY_LEVEL == 2
    assert clamp_autonomy_level("nonsense") == 2
