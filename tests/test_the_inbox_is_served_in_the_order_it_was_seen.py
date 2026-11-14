"""Hand-ins are asked in the order the promoter first saw them, then in the order they were handed in; never by name.

Until 2026-10-09 the promoter took the inbox in name order, so a hand-in that arrived at 00:10 was asked before one
that had waited since 23:33 (self-thomas-35e761dc9b20 and self-thomas-4d59059a5b4d, 2026-10-07), and the caged account,
which names the folders, could put any hand-in first. Now each hand-in keeps the place it had when the promoter first
saw it. The promoter looks at the inbox only between cards, and a card can be up for hours, so most hand-ins are first
seen together with others: those go in the order they were handed in (``submitted_at``), then by name. Hand-ins
waiting together share one card (your decision, 2026-10-08: "Yes, batch cards"), whose lines keep this order.

A hand-in that makes a pass fail gets its own verdict: it never stays first in the inbox, stopping every one behind it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks

from tests.test_a_self_fix_lands_only_when_you_approve import (  # noqa: F401
    Asker,
    _outbox,
    _promoter,
    _submit,
    blue,
    pins,
)


def _asked_for(asked: list[tuple[str, str]]) -> list[str]:
    """Each of thomas/a.py, b.py and c.py the cards asked about, card by card, in the order each card shows them."""
    found: list[str] = []
    for action, _ in asked:
        found += sorted((p for p in ("thomas/a.py", "thomas/b.py", "thomas/c.py") if p in action), key=action.index)
    return found


def test_a_hand_in_seen_first_is_asked_first_whatever_its_name(blue: Path, pins: Path) -> None:
    ask = Asker(True, True)
    promoter = _promoter(blue, pins, ask)
    later = _submit(blue, "exec-zz-waited-longest", {"thomas/b.py": "B = 1\n"})
    assert [p.name for p in promoter.pending()] == [later.name]
    sooner = _submit(blue, "exec-aa-arrived-later", {"thomas/a.py": "A = 1\n"})

    assert [p.name for p in promoter.pending()] == [later.name, sooner.name]
    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]
    assert len(ask.asked) == 1 and not later.exists() and not sooner.exists(), "both on one shared card"
    assert _asked_for(ask.asked) == ["thomas/b.py", "thomas/a.py"]


def test_hand_ins_waiting_at_start_are_taken_in_the_order_they_were_handed_in(blue: Path, pins: Path) -> None:
    _submit(blue, "exec-zz", {"thomas/b.py": "B = 1\n"})
    _submit(blue, "exec-aa", {"thomas/a.py": "A = 1\n"})
    ask = Asker(True, True)
    promoter = _promoter(blue, pins, ask)

    promoter.run_once()
    promoter.run_once()

    assert _asked_for(ask.asked) == ["thomas/b.py", "thomas/a.py"]


def test_hand_ins_that_arrive_while_a_card_is_up_keep_their_arrival_order(blue: Path, pins: Path) -> None:
    """Overnight 2026-10-07 four hand-ins arrived while one card was up, from 23:33 to 00:10; with first-seen order
    alone, all four were first seen in one pass and went by name, 00:10 before 23:33."""
    _submit(blue, "exec-card-up", {"thomas/fix_me.py": "VALUE = 2\n"})
    arrived: list[str] = []

    class AskAndArrive(Asker):
        def __call__(self, action: str, reason: str) -> bool:
            if not self.asked:  # while the first card is up
                arrived.append(_submit(blue, "exec-zz-arrived-first", {"thomas/b.py": "B = 1\n"}).name)
                arrived.append(_submit(blue, "exec-aa-arrived-second", {"thomas/a.py": "A = 1\n"}).name)
            return super().__call__(action, reason)

    ask = AskAndArrive(True, True, True)
    promoter = _promoter(blue, pins, ask)

    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]
    assert [p.name for p in promoter.pending()] == arrived
    promoter.run_once()
    promoter.run_once()
    assert _asked_for(ask.asked[1:]) == ["thomas/b.py", "thomas/a.py"]


def test_a_new_name_cannot_jump_the_queue(blue: Path, pins: Path) -> None:
    ask = Asker(True, True, True)
    promoter = _promoter(blue, pins, ask)
    _submit(blue, "exec-mm", {"thomas/b.py": "B = 1\n"})
    _submit(blue, "exec-nn", {"thomas/c.py": "C = 1\n"})
    promoter.pending()
    _submit(blue, "exec-00000-first-by-name", {"thomas/a.py": "A = 1\n"})

    for _ in range(3):
        promoter.run_once()

    assert _asked_for(ask.asked) == ["thomas/b.py", "thomas/c.py", "thomas/a.py"]


# -- one hand-in never holds up the rest ------------------------------------------------------------------------ #


def test_a_manifest_json_cannot_read_gets_its_verdict_and_the_queue_moves_on(blue: Path, pins: Path) -> None:
    """Nested deeper than json reads, a manifest raised RecursionError, which nothing caught: every pass failed on
    the same hand-in, first in the inbox, and none behind it was ever asked."""
    poisoned = _submit(blue, "exec-poison", {"thomas/a.py": "A = 1\n"})
    good = _submit(blue, "exec-good", {"thomas/b.py": "B = 1\n"})
    ask = Asker(True)
    promoter = _promoter(blue, pins, ask)
    assert [p.name for p in promoter.pending()] == [poisoned.name, good.name]
    (poisoned / "submission.json").write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")

    first = promoter.run_once()
    second = promoter.run_once()

    assert first is not None and first.status == "refused" and "could not be read" in first.detail, first
    assert _outbox(poisoned.name, "verdict")["status"] == "refused" and not poisoned.exists()
    assert second is not None and second.status == "landed", second
    assert _asked_for(ask.asked) == ["thomas/b.py"]


def test_any_failure_in_a_pass_is_that_hand_ins_own_verdict(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _submit(blue, "exec-breaks-a-check", {"thomas/a.py": "A = 1\n"})
    good = _submit(blue, "exec-after-it", {"thomas/b.py": "B = 1\n"})
    real = checks.import_break_refusal

    def breaks_on_a(repo, parent, tree, changes):  # noqa: ANN001, ANN202 - as import_break_refusal
        if any(path == "thomas/a.py" for _, path in changes):
            raise KeyError("a check broke")
        return real(repo, parent, tree, changes)

    monkeypatch.setattr(checks, "import_break_refusal", breaks_on_a)
    ask = Asker(True)
    promoter = _promoter(blue, pins, ask)

    broke = promoter.run_once()
    landed = promoter.run_once()

    assert broke is not None and broke.status == "error" and "KeyError" in broke.detail, broke
    assert not first.exists() and _outbox(first.name, "verdict")["status"] == "error"
    assert landed is not None and landed.status == "landed" and not good.exists(), landed
    assert _asked_for(ask.asked) == ["thomas/b.py"]
