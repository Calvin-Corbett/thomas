"""THOMAS_SECOND_LOOKS is the dial each server reads for itself, and a dial of 1 lets one second look run at once.

Part of SC4 (spec Part 1 item 6; thomas/server/precard/review_dial.py). Both servers must be started with the same
value: each counts the second looks of both against the number it reads. A turn that ignored the setting and took 2
would let the second of these two look run while the first holds its turn.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from thomas.server import capacity_ledger, green_checkout
from thomas.server.precard import review_dial


def _wait_until(test: Callable[[], bool], within: float = 10.0) -> None:
    ends = time.monotonic() + within
    while not test():
        assert time.monotonic() < ends, "it never happened"
        time.sleep(0.01)


def test_with_the_dial_at_one_a_second_look_waits_while_another_holds_its_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "greens"))
    monkeypatch.setenv(review_dial.SECOND_LOOKS_ENV, "1")
    monkeypatch.setattr(capacity_ledger, "POLL_S", 0.02)
    holding, release, ran = threading.Event(), threading.Event(), []

    def look(name: str, keep_its_turn: bool) -> None:
        with review_dial.turn():
            ran.append(name)
            if keep_its_turn:
                holding.set()
                assert release.wait(20)

    first = threading.Thread(target=look, args=("first", True))
    first.start()
    assert holding.wait(10)
    second = threading.Thread(target=look, args=("second", False))
    second.start()

    try:
        _wait_until(lambda: review_dial.running() + review_dial.waiting() == 2)  # the second has asked for its turn
        time.sleep(0.5)  # 25 passes of the ledger: a dial of 2 would have let it in on the first
        assert review_dial.running() == 1 and review_dial.waiting() == 1 and ran == ["first"], "it waits for the turn"
    finally:
        release.set()
        first.join(20)
        second.join(20)

    assert ran == ["first", "second"] and review_dial.running() == 0
