"""The window's lane takes up only what an open window may land, and the card loop keeps everything else.

No one outside Thomas holds a change aside for a window: while one is open the lane takes up every hand-in no card has
taken, under the card loop's own lock, and hands every one back when the window ends or cannot be relied on. The world,
its stand-ins and fixtures are the lane's own (tests/test_a_checked_change_lands_inside_your_window.py).
"""

from __future__ import annotations

from pathlib import Path

from scripts.cage import self_change_promoter as sp

from tests.test_a_checked_change_lands_inside_your_window import (  # noqa: F401 - fixtures
    SID,
    World,
    _hand_in,
    blue,
    pins,
    world,
)
from thomas.tools import cage_shell


def test_with_no_window_open_the_lane_takes_nothing_and_the_cards_keep_it(world: World) -> None:
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})

    assert world.run(passes=5) is None and sub.exists()
    assert world.lane.owned() == frozenset() and world.link.jobs == [] and world.lane.waiting() == []
    assert world.lane.takeable(frozenset()) == [SID], "a window opened now would take it up"
    world.open()
    assert world.run().status == "landed"  # type: ignore[union-attr]


def test_a_hand_in_on_a_card_is_never_taken_up(world: World) -> None:
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()
    assert world.run(busy=frozenset({SID}), passes=5) is None and sub.exists() and world.link.jobs == []
    assert world.lane.owned() == frozenset() and world.lane.takeable(frozenset({SID})) == []


def test_when_the_window_ends_every_change_it_took_goes_back_to_the_cards(world: World) -> None:
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()
    assert world.run(allowed=False, passes=5) is None and SID in world.lane.owned()
    forgotten = len(world.link.forgotten)

    world.window.close("you closed it")
    assert world.run(passes=1) is None

    assert world.lane.owned() == frozenset() and world.lane.waiting() == [] and sub.exists()
    assert len(world.link.forgotten) == forgotten + 1, "its checker job is no longer wanted"


def test_a_window_the_loop_cannot_rely_on_hands_every_change_back_to_the_cards(world: World) -> None:
    _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()
    assert world.run(allowed=False, passes=3) is None and SID in world.lane.owned()
    assert world.run(reliable=False, passes=1) is None and world.lane.owned() == frozenset()


def test_the_card_loop_leaves_alone_what_the_window_owns_and_says_what_it_took_up(blue: Path, pins: Path) -> None:
    _hand_in(blue, {"thomas/fix_me.py": "VALUE = 2\n"}, "self-thomas-aaaaaaaaaaaa")
    _hand_in(blue, {"thomas/other.py": "X = 1\n"}, "self-thomas-bbbbbbbbbbbb")
    seen: list[frozenset[str]] = []
    card = sp.Promoter(repo=blue, cage_root=cage_shell.cage_root(), ask=lambda a, r: False, pin_root=pins,
                       audit=lambda _r: [], skip=lambda: frozenset({"self-thomas-aaaaaaaaaaaa"}))  # fmt: skip

    assert [sub.name for sub in card.pending()] == ["self-thomas-bbbbbbbbbbbb"]
    card.promote = lambda sub: seen.append(card.busy) or sp.Outcome("declined")  # type: ignore[method-assign]
    card.run_once()
    assert seen == [frozenset({"self-thomas-bbbbbbbbbbbb"})] and card.busy == frozenset()


def test_the_card_loop_picks_its_hand_ins_under_the_lock_the_lane_takes_them_under(blue: Path, pins: Path) -> None:
    """With no one holding a change aside first, the lane and the card loop decide in turn: while one holds the lock
    the other cannot pick, so no hand-in is ever both a card's and the window's."""
    _hand_in(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    card = sp.Promoter(repo=blue, cage_root=cage_shell.cage_root(), ask=lambda a, r: False, pin_root=pins,
                       audit=lambda _r: [])  # fmt: skip
    held: list[bool] = []
    pending = card.pending
    card.pending = lambda: held.append(card.taking.locked()) or pending()  # type: ignore[method-assign]
    card.promote = lambda sub: sp.Outcome("declined")  # type: ignore[method-assign]
    card.run_once()
    assert held == [True] and not card.taking.locked()
