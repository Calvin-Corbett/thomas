"""A hand-in held for your plan's usage limit waits for the reset, and every held one says when second looks resume.

Part of SC4 (spec Part 1 item 6). The second look's turns and the pause are
tests/test_second_looks_take_turns_and_wait_out_a_usage_limit.py; this is what the hold
(thomas/server/hand_in_hold.py) does with the reset the pause names: the row waits until then, not 900 s (never past
the 31 days a reset is believed), and the words your list and the chat card show name the time while second looks are
paused. Those words are read without the ledger's lock, because a steer reaches them on the event loop.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from tests import hand_in_hold_support as support
from thomas.core.provider_limits import when_words
from thomas.server import capacity_ledger, capacity_ledger_locks, hand_in_hold
from thomas.server.precard import review, review_dial

DIRECTORY = object()  # a pause "file" that is a folder: reading it raises an OSError


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The second-look pause a held row's words read lives in this test's own ledger folder, never the real one,
    and a pause made here records no issue."""
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(review_dial, "notice", lambda *_a: None)


def _booked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> support.Project:
    project = support.make_project(tmp_path, monkeypatch)
    support.book(project)
    return project


def test_a_usage_limited_hold_waits_for_the_reset_and_shows_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = support.make_project(tmp_path, monkeypatch)
    support.book(project)
    work, catalog, cid = project
    reset = time.time() + 3 * 3600

    held = hand_in_hold.hold(work, catalog, cid, "second look", review.limited_words(reset, False), costly=False,
                             until=reset)  # fmt: skip

    assert held is not None and held["next_at"] == reset and held["strikes"] == 0 and held["tries"] == 1
    _phase, words = hand_in_hold.phase(work, catalog, cid)
    assert time.strftime("%Y-%m-%d %H:%M", time.localtime(reset)) in words and when_words(reset) in words
    assert support.tick(project) == [], "nothing asks again before the reset"


def test_a_hold_with_no_reset_still_tries_again_in_fifteen_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = support.make_project(tmp_path, monkeypatch)
    support.book(project)
    work, catalog, cid = project
    before = time.time()

    held = hand_in_hold.hold(work, catalog, cid, "check", "no interpreter", costly=False)

    assert held is not None and before + hand_in_hold.RETRY_S <= held["next_at"] <= time.time() + hand_in_hold.RETRY_S


@pytest.mark.parametrize(
    "offset", [-60.0, 40 * 86400.0, float("nan")], ids=["already over", "beyond what a reset is believed", "no time"]
)
def test_a_reset_that_is_over_or_beyond_belief_is_not_waited_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offset: float
) -> None:
    work, catalog, cid = _booked(tmp_path, monkeypatch)
    before = time.time()

    held = hand_in_hold.hold(work, catalog, cid, "second look", "a limit", costly=False, until=before + offset)

    assert held is not None and before + hand_in_hold.RETRY_S <= held["next_at"] <= time.time() + hand_in_hold.RETRY_S


def test_every_held_hand_in_shows_when_second_looks_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = support.make_project(tmp_path, monkeypatch)
    support.book(project)
    work, catalog, cid = project
    reset = time.time() + 7200
    review_dial.pause(reset)

    hand_in_hold.hold(work, catalog, cid, "check", "no interpreter", costly=False)

    state, words = hand_in_hold.phase(work, catalog, cid)
    assert state == "paused" and words.startswith("Held before your approval card: check could not run")
    assert f"usage limit until {when_words(reset)}" in words and "Thomas looks again" not in words


def test_a_held_hand_in_says_when_thomas_looks_again_when_the_reset_is_an_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = _booked(tmp_path, monkeypatch)
    reset = time.time() + 7200
    review_dial.pause(reset, estimated=True)

    hand_in_hold.hold(work, catalog, cid, "check", "no interpreter", costly=False)

    _state, words = hand_in_hold.phase(work, catalog, cid)
    assert f"Thomas looks again {when_words(reset)}" in words and f"until {when_words(reset)}" not in words


def test_the_reset_is_shown_while_another_server_holds_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = _booked(tmp_path, monkeypatch)
    reset = time.time() + 7200
    review_dial.pause(reset)
    hand_in_hold.hold(work, catalog, cid, "check", "no interpreter", costly=False)
    shown: list[tuple[str, str] | None] = []
    steer = threading.Thread(target=lambda: shown.append(hand_in_hold.phase(work, catalog, cid)))

    with capacity_ledger_locks.locked(capacity_ledger.folder(), capacity_ledger.NAME):  # a turn is being given out
        steer.start()
        steer.join(10)
        returned = not steer.is_alive()
    steer.join(10)

    assert returned, "a steer on the event loop must not wait for the ledger's lock"
    assert shown and shown[0] is not None and when_words(reset) in shown[0][1]
    assert review_dial.pause_shown() == (reset, False), "the reset, and that it is not an estimate"


@pytest.mark.parametrize(
    "kept",
    [None, "{not json", "[]", '{"until": "soon"}', '{"until": PAST}', '{"until": FAR}', DIRECTORY],
    ids=["missing", "garbled", "not an object", "not a time", "already over", "beyond belief", "unreadable"],
)
def test_a_pause_that_cannot_be_shown_leaves_the_base_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kept: object
) -> None:
    work, catalog, cid = _booked(tmp_path, monkeypatch)
    pause_file = capacity_ledger.folder() / review_dial.PAUSE_NAME
    pause_file.parent.mkdir(parents=True, exist_ok=True)
    if kept is DIRECTORY:
        pause_file.mkdir()
    elif isinstance(kept, str):
        text = kept.replace("PAST", str(time.time() - 60)).replace("FAR", str(time.time() + 40 * 86400))
        pause_file.write_text(text, encoding="utf-8")
    hand_in_hold.hold(work, catalog, cid, "check", "no interpreter", costly=False)

    state, words = hand_in_hold.phase(work, catalog, cid)

    assert review_dial.pause_shown() is None
    assert state == "paused" and words.endswith("(try 1)") and "Second looks wait" not in words


def test_a_pause_read_that_fails_leaves_the_base_words(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, catalog, cid = _booked(tmp_path, monkeypatch)
    hand_in_hold.hold(work, catalog, cid, "check", "no interpreter", costly=False)

    def unreadable(_place: Path) -> dict:
        raise capacity_ledger_locks.LedgerUnreadable("the ledger cannot be read")  # an OSError

    monkeypatch.setattr(review_dial, "_read_pause", unreadable)

    state, words = hand_in_hold.phase(work, catalog, cid)

    assert state == "paused" and words.endswith("(try 1)") and "Second looks wait" not in words
