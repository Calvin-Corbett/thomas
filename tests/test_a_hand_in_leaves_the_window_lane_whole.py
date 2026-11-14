"""A hand-in leaves the window lane whole: sent to its card, taken out of the inbox, or changed under it (2026-10-14
review, RH-R7 and WS-V missed-4).

Nothing the lane gathered for a hand-in outlives its leaving: the Build teams' account chooses hand-in ids, so a later
hand-in under the same id must meet nothing it was never given. The world, its stand-ins and fixtures are the lane's
own (tests/test_a_checked_change_lands_inside_your_window.py).
"""

from __future__ import annotations

from scripts.cage import window_lane as wl
from scripts.cage.window_rules import Rules

from tests.green_support import git
from tests.test_a_checked_change_lands_inside_your_window import (  # noqa: F401 - fixtures
    SID,
    World,
    _hand_in,
    blue,
    pins,
    world,
)
from thomas.tools import cage_shell


def _fresh_lane(world: World) -> wl.Lane:
    """The lane after a promoter restart: nothing it held in memory survives."""
    return wl.Lane(world.promoter, link=world.link, reviewer=world.reviewer, rules=Rules(world.blue, modules={}),
                   record=world.record)  # fmt: skip


def test_a_change_the_lane_sends_to_its_card_is_never_taken_up_again(world: World) -> None:
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n", "scripts/cage/new_rule.py": "RULE = 1\n"})
    world.open()

    assert world.run(passes=3) is None and sub.exists()

    assert SID not in world.lane.owned(), "released to its card"
    assert world.run(passes=2) is None and SID not in world.lane.owned(), "and not taken up on the next pass"
    assert SID not in _fresh_lane(world).owned(), "a restarted promoter owns nothing: it is on its card at once"


def test_a_hand_in_taken_out_of_the_inbox_leaves_nothing_behind(world: World) -> None:
    before = git(world.blue, "rev-parse", "dev")
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()
    assert world.run(allowed=False, passes=3) is None and len(world.link.jobs) == 1  # checked and read
    held = cage_shell.cage_root() / "withdrawn" / SID
    held.parent.mkdir(parents=True, exist_ok=True)
    sub.rename(held)

    assert world.run(passes=2) is None

    assert SID not in world.lane.owned() and world.lane.waiting() == []
    assert world.link.forgotten == [world.link.jobs[0].id], "its checker job is no longer wanted"
    held.rename(sub)  # the same id again: it is a new hand-in, checked and read from the start
    assert world.run(allowed=False, passes=3) is None and len(world.link.jobs) == 2
    assert git(world.blue, "rev-parse", "dev") == before


def test_after_dev_moves_under_it_the_change_is_read_and_checked_again_and_lands_what_was_read(world: World) -> None:
    """A three-way apply onto a dev that moved on the same file lands other bytes: the second look of the old change
    never counts for the new one, and the landing records the change its look and its check were of."""
    lines = [f"L{n} = {n}\n" for n in range(30)]
    (world.blue / "thomas" / "lines.py").write_text("".join(lines), encoding="utf-8")
    git(world.blue, "add", "-A")
    git(world.blue, "commit", "-qm", "lines")
    team = list(lines)
    team[2] = "L2 = 22\n"
    _hand_in(world.blue, {"thomas/lines.py": "".join(team)})
    world.open()
    assert world.run(allowed=False, passes=3) is None
    first = world.lane._preps[SID].change
    moved = list(lines)
    moved[27] = "L27 = 72\n"
    (world.blue / "thomas" / "lines.py").write_text("".join(moved), encoding="utf-8")
    git(world.blue, "commit", "-qam", "dev moved on the same file")

    outcome = world.run()

    assert outcome is not None and outcome.status == "landed", outcome
    landed = [event for event in world.record.events() if event["name"] == "landed"][0]
    assert landed["change"] != first and landed["second_look_change"] == landed["change"]
    assert len(world.reviewer.read) == 2 and len(world.link.jobs) == 2, "read and checked again"
