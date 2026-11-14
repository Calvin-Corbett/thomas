"""When the approval cards do not match their pin, every hand-in waits: nothing is asked, refused or landed.

On 2026-10-08 self-thomas-eb0e79c9d549 was refused during a re-pin: for the few minutes the catalogue file and its pin
differed, the promoter refused every hand-in it took up ("the approval catalogue is tampered"), and the team had to hand
it in again. A mismatch is a state of the machine, not a fault in the change, so now the hand-in stays in the inbox and
is asked once the cards match their pin again. The same holds when the cards changed on disk after the promoter loaded
them: it would otherwise show wording that is not the pinned one.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from tests.green_support import git
from tests.test_a_self_fix_lands_only_when_you_approve import Asker, _promoter, _submit, blue, pins  # noqa: F401
from thomas.tools import cage_shell, trusted_card


def _verdicts() -> list[Path]:
    outbox = cage_shell.cage_root() / "outbox"
    return sorted(outbox.glob("*.verdict.json")) if outbox.is_dir() else []


def test_every_hand_in_waits_while_the_pin_does_not_match(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    first = _submit(blue, "exec-wait-a", {"thomas/a.py": "A = 1\n"})
    second = _submit(blue, "exec-wait-b", {"thomas/b.py": "B = 1\n"})
    good = (pins / trusted_card.PIN_NAME).read_text()
    (pins / trusted_card.PIN_NAME).write_text("0" * 64)  # a re-pin under way
    audited: list[Path] = []
    ask = Asker(True, True)
    promoter = _promoter(blue, pins, ask, audit=lambda repo: audited.append(repo) or [])

    for _ in range(3):
        outcome = promoter.run_once()
        assert outcome is not None and outcome.status == "held", outcome
        assert "pin" in outcome.detail

    assert ask.asked == [] and audited == [], "nothing was read, audited or asked"
    assert first.is_dir() and second.is_dir() and _verdicts() == [], "nothing refused"
    assert git(blue, "rev-parse", "dev") == before

    (pins / trusted_card.PIN_NAME).write_text(good)  # the re-pin is done
    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]
    assert len(ask.asked) == 1, "both on one shared card"
    assert not first.exists() and not second.exists()


def test_cards_never_pinned_on_this_machine_hold_too(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-unpinned", {"thomas/fix_me.py": "VALUE = 2\n"})
    (pins / trusted_card.PIN_NAME).unlink()
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "held" and "unpinned" in outcome.detail, outcome
    assert ask.asked == [] and sub.is_dir() and _verdicts() == []


def test_cards_changed_on_disk_after_loading_hold(blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The promoter loads the cards once per process: a file re-pinned and changed since then is not what it shows."""
    sub = _submit(blue, "exec-stale-cards", {"thomas/fix_me.py": "VALUE = 2\n"})
    monkeypatch.setattr(trusted_card, "_loaded", (trusted_card.load_catalogue(), "f" * 64))
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).run_once()

    assert outcome is not None and outcome.status == "held", outcome
    assert "restart the promoter" in outcome.detail
    assert ask.asked == [] and sub.is_dir() and _verdicts() == []


def test_cards_re_pinned_while_a_hand_in_is_checked_hold_it(blue: Path, pins: Path) -> None:
    """The writer audit alone can take two minutes: a pin that stops matching during the checks holds the card too."""
    sub = _submit(blue, "exec-re-pinned", {"thomas/fix_me.py": "VALUE = 2\n"})

    def re_pin_under_way(_repo: Path) -> list[str]:
        (pins / trusted_card.PIN_NAME).write_text("0" * 64)
        return []

    ask = Asker(True)
    outcome = _promoter(blue, pins, ask, audit=re_pin_under_way).run_once()

    assert outcome is not None and outcome.status == "held", outcome
    assert ask.asked == [] and sub.is_dir() and _verdicts() == []


def test_a_hold_is_said_once_not_every_pass(blue: Path, pins: Path, caplog: pytest.LogCaptureFixture) -> None:
    _submit(blue, "exec-said-once", {"thomas/fix_me.py": "VALUE = 2\n"})
    (pins / trusted_card.PIN_NAME).write_text("0" * 64)
    promoter = _promoter(blue, pins, Asker(True))

    with caplog.at_level(logging.WARNING, logger="thomas.self_change_promoter"):
        for _ in range(4):
            promoter.run_once()

    assert len([r for r in caplog.records if "holding every hand-in" in r.getMessage()]) == 1


def test_an_empty_inbox_is_not_held(blue: Path, pins: Path) -> None:
    (pins / trusted_card.PIN_NAME).write_text("0" * 64)
    assert _promoter(blue, pins, Asker(True)).run_once() is None
