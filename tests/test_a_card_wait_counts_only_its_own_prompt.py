"""A card's measured prompt is its own, never the wait behind the window's prompt.

The window's loop runs beside the card loop and both ask through one asker (scripts/cage/window_loop.py, OnePrompt): one
Windows sign-in at a time. Each completed card prompt is also recorded as an interval in the hand-in's pending record, the
project list's "waiting for your card" (prompt intervals, not queue time). Measured from before that asker's lock, a card
that waited behind a window card -- a revert card stays up until you are back -- counted the whole wait as its own.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from scripts.cage import self_change_promoter as sp
from scripts.cage.window_loop import OnePrompt


def _promoter(tmp_path: Path, ask: object) -> sp.Promoter:
    p = sp.Promoter(cage_root=tmp_path / "cage", ask=ask)  # type: ignore[arg-type]
    p._meta, p._sub_dir = {"id": "self-wait"}, tmp_path / "self-wait"
    return p


def test_a_card_waiting_behind_the_windows_prompt_counts_only_its_own_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    card_read_the_clock = threading.Event()

    def clock() -> float:
        if threading.current_thread().name == "card":
            card_read_the_clock.set()
        return now[0]

    monkeypatch.setattr(time, "time", clock)
    window_up, window_answered = threading.Event(), threading.Event()

    def windows_prompt(action: str, reason: str) -> str:
        if action == "open_window":
            window_up.set()
            assert window_answered.wait(10), "the test never answered the window's card"
        return "approved"

    asker = OnePrompt(windows_prompt)
    p = _promoter(tmp_path, asker)
    intervals: list[tuple[float, float]] = []
    answers: list[str] = []

    window = threading.Thread(target=asker, args=("open_window", "your window"), name="window")
    window.start()
    assert window_up.wait(10)
    card = threading.Thread(
        target=lambda: answers.append(
            p._sign_in("promote_batch", "a hand-in's card", "again", observed=lambda s, e: intervals.append((s, e)))
        ),
        name="card",
    )
    card.start()
    assert card_read_the_clock.wait(10), "the card never reached its prompt"
    now[0] = 2000.0  # the window's card stays up meanwhile; the card waits behind it
    window_answered.set()
    window.join(10)
    card.join(10)

    assert answers == ["approved"]
    assert intervals == [(2000.0, 2000.0)], "the wait behind the window's card is not this card's prompt"


def test_an_asker_with_no_turn_clock_is_timed_from_the_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [500.0]
    monkeypatch.setattr(time, "time", lambda: now[0])

    def prompt(action: str, reason: str) -> str:
        now[0] = 530.0
        return "cancelled"

    p = _promoter(tmp_path, prompt)
    intervals: list[tuple[float, float]] = []
    assert p._sign_in("promote_batch", "card", "again", observed=lambda s, e: intervals.append((s, e))) == "cancelled"
    assert intervals == [(500.0, 530.0)]


def test_a_prompt_that_failed_records_no_interval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "_TRIES", 1)
    p = _promoter(tmp_path, OnePrompt(lambda action, reason: "failed"))
    intervals: list[tuple[float, float]] = []
    assert p._sign_in("promote_batch", "card", "again", observed=lambda s, e: intervals.append((s, e))) == "failed"
    assert intervals == []
