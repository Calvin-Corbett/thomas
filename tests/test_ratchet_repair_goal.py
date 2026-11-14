"""A repair goal carries every conflict, failure, and constraint."""

from __future__ import annotations

from pathlib import Path

from tests.ratchet_support import candidate
from thomas.server.ratchet.attempt import Attempt
from thomas.server.ratchet.proof import Verdict
from thomas.server.ratchet.repair import repair_goal
from thomas.server.ratchet.screen import Conflict, Screen


def test_the_goal_carries_every_constraint_and_failure(tmp_path: Path) -> None:
    found = Screen(
        "d" * 40,
        "c" * 40,
        "t" * 40,
        conflicts=(Conflict("tests/a.py", "candidate_deleted", "keep dev's file"),),
        resurrected=("thomas/old.py (dev deleted it in 1234567)",),
        duplicate_tests=("tests/b.py::test_one",),
        flags=("a conflict marker in docs/x.md",),
    )
    att = Attempt(candidate("c" * 40, "refs/heads/praxis/x"), "d" * 40, found, None)  # type: ignore[arg-type]
    failing = ("tests/c.py::test_c", "tests/d.py::test_d")
    verdict = Verdict(False, "2 new failure(s)", new_failures=failing, flaky=("tests/d.py::test_d",))

    goal = repair_goal(att, verdict)

    for text in (
        "refs/heads/praxis/x",
        "tests/a.py: keep dev's file",
        "thomas/old.py",
        "tests/b.py::test_one",
        "a conflict marker in docs/x.md",
        "tests/c.py::test_c",
        "WORKBOARD",
        "pass when run alone",
    ):
        assert text in goal
    assert "- tests/d.py::test_d" in goal.split("pass when run alone", 1)[1]
