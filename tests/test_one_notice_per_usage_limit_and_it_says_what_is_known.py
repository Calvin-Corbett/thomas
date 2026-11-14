"""You get one notice each time your plan's usage limit is reached, however long it lasts, and it says what is known.

Part of SC4 (spec Part 1 item 6; the pause is thomas/server/precard/review_dial.py). A limit is one episode: it begins
at the first pause after a second look that succeeded (or when no pause has been kept yet) and ends when a second
look succeeds while no pause is in force. A pause that comes back inside the episode, because the reset passed and
the limit was met again, gives no new notice; a limit met after a success does. The notice says when Thomas looks
again, not a reset, whenever Thomas could not read an exact reset time from the CLI, and a bare time printed just
before now is never read as tomorrow's.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from thomas.core.provider_limits import when_words
from thomas.server import capacity_ledger
from thomas.server.precard import review_dial

T = 1_800_000_000.0
HOUR = 3600.0


@pytest.fixture(autouse=True)
def now(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """This test's own ledger folder, and a clock it moves: element 0 is the time on the dial's clock."""
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    moment = [T]
    monkeypatch.setattr(review_dial, "clock", lambda: moment[0])
    return moment


@pytest.fixture
def notices(monkeypatch: pytest.MonkeyPatch) -> list[tuple[float, bool]]:
    seen: list[tuple[float, bool]] = []
    monkeypatch.setattr(review_dial, "notice", lambda until, estimated, _waiting: seen.append((until, estimated)))
    return seen


def _noticed() -> bool:
    return bool(json.loads((capacity_ledger.folder() / review_dial.PAUSE_NAME).read_text(encoding="utf-8"))["noticed"])


def test_one_limit_gives_one_notice_even_when_a_second_look_is_answered_during_it(
    notices: list[tuple[float, bool]],
) -> None:
    assert review_dial.pause(T + HOUR) is True

    review_dial.answered()  # a second look that was already running when the limit was met got its answer
    assert _noticed(), "an answer during a pause does not end its notice"
    assert review_dial.pause(T + HOUR) is False, "another second look met the same limit"
    assert review_dial.pause(T + 2 * HOUR) is False, "and the reset moved later"

    assert notices == [(T + HOUR, False)]
    assert review_dial.pause_shown() == (T + 2 * HOUR, False)


def test_a_limit_that_comes_back_before_any_answer_gives_no_new_notice_and_one_after_an_answer_does(
    notices: list[tuple[float, bool]], now: list[float]
) -> None:
    assert review_dial.pause(T + HOUR) is True

    now[0] = T + HOUR + 1  # the pause has ended, and no second look has been answered since
    assert review_dial.pause_shown() is None
    assert review_dial.pause(T + 3 * HOUR, estimated=True) is False, "the limit came back: the same episode"

    now[0] = T + 3 * HOUR + 1
    review_dial.answered()  # an answer after the pause ended: the episode is over, and its notice with it
    assert not _noticed()
    assert review_dial.pause(T + 5 * HOUR) is True, "a limit met after a success is a new episode"

    assert notices == [(T + HOUR, False), (T + 5 * HOUR, False)]


def test_the_notice_names_the_reset_when_the_cli_gave_one(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict] = []
    monkeypatch.setattr("thomas.server.issue_ledger.record_issue", lambda **kwargs: recorded.append(kwargs))

    review_dial._record_notice(T + HOUR, False, 3)

    [issue] = recorded
    assert issue["kind"] == "second_looks_paused" and issue["context"] == {"until": round(T + HOUR), "waiting": 3}
    assert f"until it resets {when_words(T + HOUR)}" in issue["message"]
    assert "looks again" not in issue["message"] and "estimated" not in issue["message"]


def test_the_notice_says_when_thomas_looks_again_when_no_exact_reset_could_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict] = []
    monkeypatch.setattr("thomas.server.issue_ledger.record_issue", lambda **kwargs: recorded.append(kwargs))

    review_dial._record_notice(T + HOUR, True, 0)

    [issue] = recorded
    assert "Thomas could not read an exact reset time from the CLI" in issue["message"]
    assert "the CLI gave no" not in issue["message"], "a reset with a zone Thomas cannot read was still given"
    assert f"Thomas looks again {when_words(T + HOUR)}" in issue["message"]
    assert "until it resets" not in issue["message"] and "estimated" not in issue["message"]


def test_a_reset_printed_for_a_moment_just_past_is_not_read_as_tomorrow() -> None:
    printed = datetime.fromtimestamp(T).astimezone().replace(hour=12, minute=20, second=0, microsecond=0).timestamp()
    said = "You've hit your session limit · resets 12:20pm"  # no zone: read on this machine's clock, an hour on

    assert review_dial.plan_reset(said, now=printed + 5) == (printed + HOUR, True)
    assert review_dial.plan_reset(said, now=printed + HOUR + 5) == (printed + HOUR + 5 + review_dial.RECHECK_S, True)
