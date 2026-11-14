"""A window lands only what its second look read and its checker passed, in the bytes they were given (2026-10-14
review).

The window-security, card-flow and rehearsal reviewers of 2026-10-14 found ways a window could land what nothing had
read: bytes rewritten after they were read, a second look of an older derivation counting for the change that landed,
and a hand-in that already had a verdict landing again. Each test is one of their scenarios. The world, its stand-ins
and fixtures are the lane's own (tests/test_a_checked_change_lands_inside_your_window.py).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from scripts.cage import self_change_promoter as sp
from scripts.cage import window_evidence as we
from scripts.cage import window_review as wrev

from tests.green_support import git
from tests.test_a_checked_change_lands_inside_your_window import (  # noqa: F401 - fixtures
    SID,
    FakeLink,
    FakeReviewer,
    World,
    _hand_in,
    blue,
    pins,
    world,
)
from thomas.tools import cage_shell


def test_bytes_rewritten_after_they_were_read_are_read_and_checked_again_before_anything_lands(world: World) -> None:
    """2026-10-14 review, WS-R2: the cage's account can rewrite a hand-in in the inbox after the lane read it. New bytes
    are a new change: nothing gathered for the old ones counts, and what lands is what was read and checked."""
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()
    assert world.run(allowed=False, passes=3) is None and len(world.link.jobs) == 1
    git(world.blue, "checkout", "-q", "-B", "swap", "dev")
    (world.blue / "thomas" / "fix_me.py").write_text("VALUE = 'rewritten'\n", encoding="utf-8")
    git(world.blue, "commit", "-qam", "swap")
    swapped = subprocess.run(
        ["git", "diff", "--binary", "--full-index", "dev", "swap"], cwd=world.blue, capture_output=True
    ).stdout
    git(world.blue, "checkout", "-q", "dev")
    (sub / "change.patch").write_bytes(swapped)
    manifest = json.loads((sub / "submission.json").read_text(encoding="utf-8"))
    (sub / "submission.json").write_text(
        json.dumps({**manifest, "patch_sha256": hashlib.sha256(swapped).hexdigest()}), encoding="utf-8"
    )

    outcome = world.run()

    assert outcome is not None and outcome.status == "landed", outcome
    assert len(world.link.jobs) == 2 and len(world.reviewer.read) == 2, "the new bytes were checked and read"
    assert world.link.jobs[0].id in world.link.forgotten, "the old bytes' check no longer counts"
    landed = git(world.blue, "show", "dev:thomas/fix_me.py")
    assert landed == "VALUE = 'rewritten'" and world.link.jobs[1].tree == git(world.blue, "rev-parse", "dev^{tree}")


class SlowReviewer:
    """A second look that takes its time, as the real one does (up to 25 minutes on its one worker)."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = threading.Event()
        self.read: list[tuple[str, str]] = []

    def review(self, *, change: str, commit: str, summary: str, diff: str) -> wrev.Review:
        self.read.append((change, commit))
        self.started.set()
        self.release.wait(30)
        return wrev.Review(change, wrev.SAFE)


def test_a_second_look_of_an_older_derivation_never_counts_for_the_change_that_lands(
    blue: Path, pins: Path, tmp_path: Path
) -> None:
    """2026-10-14 review, WS-R1, PR-R1, RH-R4: the look started on C1; dev moved on the same file, giving C2; the look
    of C1 finished SAFE and C2 landed on it, its diff never read."""
    lines = [f"LINE_{n} = {n}\n" for n in range(20)]
    (blue / "thomas" / "fix_me.py").write_text("".join(lines), encoding="utf-8")
    git(blue, "commit", "-qam", "twenty lines")
    reviewer = SlowReviewer()
    world = World(blue, pins, tmp_path, FakeLink(), reviewer)  # type: ignore[arg-type]
    team = list(lines)
    team[1] = "LINE_1 = 'team'\n"
    _hand_in(blue, {"thomas/fix_me.py": "".join(team)})
    world.open()
    for _ in range(100):  # until the second look is reading C1
        world.run(passes=1)
        if reviewer.started.wait(0.05):
            break
    c1 = world.lane._preps[SID].change
    other = list(lines)
    other[18] = "LINE_18 = 'other'\n"
    (blue / "thomas" / "fix_me.py").write_text("".join(other), encoding="utf-8")
    git(blue, "commit", "-qam", "someone else landed the same file")
    assert world.run(passes=3) is None
    c2 = world.lane._preps[SID].change
    reviewer.release.set()

    outcome = world.run(passes=200)

    assert c1 != c2 and outcome is not None and outcome.status == "landed", outcome
    assert [change for change, _ in reviewer.read] == [c1, c2], "C2 was read before it landed"
    assert "LINE_18 = 'other'" in git(blue, "show", f"{reviewer.read[1][1]}:thomas/fix_me.py"), "it read dev's line"


class OtherChangeReviewer:
    def __init__(self) -> None:
        self.read = 0

    def review(self, *, change: str, commit: str, summary: str, diff: str) -> wrev.Review:
        self.read += 1
        return wrev.Review("f" * 64, wrev.SAFE)


def test_a_safe_second_look_of_another_change_never_counts(blue: Path, pins: Path, tmp_path: Path) -> None:
    world = World(blue, pins, tmp_path, FakeLink(), OtherChangeReviewer())  # type: ignore[arg-type]
    before = git(blue, "rev-parse", "dev")
    _hand_in(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()

    assert world.run(passes=10) is None and git(blue, "rev-parse", "dev") == before
    assert "another change" in world.lane.waiting()[0]["wait"] and world.reviewer.read == 1


class TooLargeReviewer:
    def review(self, *, change: str, commit: str, summary: str, diff: str) -> wrev.Review:
        return wrev.Review(change, wrev.TOO_LARGE, why="the change is larger than one second look can read whole")


def test_a_change_too_large_for_the_second_look_goes_to_your_card_not_back_to_its_team(
    blue: Path, pins: Path, tmp_path: Path
) -> None:
    """2026-10-26: a 37-file change was refused for what the cut-down second look could not see."""
    world = World(blue, pins, tmp_path, FakeLink(), TooLargeReviewer())  # type: ignore[arg-type]
    before = git(blue, "rev-parse", "dev")
    sub, _ = _hand_in(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()

    assert world.run(passes=10) is None and sub.exists(), "not refused: still in the inbox for its card"
    assert git(blue, "rev-parse", "dev") == before
    assert SID not in world.lane.owned() and world.lane.takeable(frozenset()) == [], "the card loop has it now"
    assert "needs its own card" in world.lane.waiting()[0]["wait"]


def test_the_lane_checks_its_second_look_was_of_this_change_just_before_it_lands(world: World) -> None:
    before = git(world.blue, "rev-parse", "dev")
    _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()

    def stale(p: object, prep: we.Prep) -> bool:
        prep.review = wrev.Review("f" * 64, wrev.SAFE)  # what an old look left behind
        return True

    world.lane.evidence.gather = stale  # type: ignore[method-assign]

    assert world.run(passes=5) is None and git(world.blue, "rev-parse", "dev") == before
    assert "second look" in world.lane.waiting()[0]["wait"]


def test_a_hand_in_your_card_decided_never_lands_in_a_window_even_put_back(
    blue: Path, pins: Path, tmp_path: Path
) -> None:
    """2026-10-14 review, PR-R8 (V4): the same hand-in folder, put back in the inbox by the cage's account after your
    Cancel on its card, must never land in your next window with no card."""
    root = cage_shell.cage_root()
    world = World(blue, pins, tmp_path, FakeLink(), FakeReviewer())
    before = git(blue, "rev-parse", "dev")
    sub, _ = _hand_in(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    saved = tmp_path / "saved"
    shutil.copytree(sub, saved)
    card = sp.Promoter(repo=blue, cage_root=root, ask=lambda a, r: False, pin_root=pins, audit=lambda _r: [])

    outcome = card.run_once()  # you press Cancel

    assert outcome is not None and outcome.status == "declined", outcome
    shutil.copytree(saved, root / "inbox" / SID)  # the cage's account puts the same hand-in back
    world.open()
    assert world.run(passes=5) is None and git(blue, "rev-parse", "dev") == before and world.link.jobs == []


@pytest.mark.parametrize("decided", ["outbox", "processed"])
def test_a_hand_in_that_already_has_a_verdict_never_lands_in_a_window(world: World, decided: str) -> None:
    root = cage_shell.cage_root()
    before = git(world.blue, "rev-parse", "dev")
    _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    if decided == "outbox":
        (root / "outbox").mkdir(parents=True, exist_ok=True)
        (root / "outbox" / f"{SID}.verdict.json").write_text("{}", encoding="utf-8")
    else:
        (root / "processed" / SID).mkdir(parents=True)
    world.open()

    assert world.run(passes=5) is None and git(world.blue, "rev-parse", "dev") == before
    assert world.link.jobs == [] and world.lane.waiting() == []


def test_a_window_landing_records_what_its_check_and_second_look_were_of(world: World) -> None:
    """2026-10-14 review (A5): the landed event kept only the second look's word, so nothing could tell a look of the
    change that landed from a look of an older one."""
    _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()

    assert world.run().status == "landed"  # type: ignore[union-attr]

    landed = [event for event in world.record.events() if event["name"] == "landed"][0]
    assert landed["second_look_change"] == landed["change"] and landed["check_verdict"] == "PASSED"
    assert landed["check_tree"] == landed["tree"] == git(world.blue, "rev-parse", "dev^{tree}")
