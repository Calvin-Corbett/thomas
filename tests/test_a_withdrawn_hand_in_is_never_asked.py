"""A hand-in taken out of the inbox is never asked about and never lands, even once the promoter has started on it.

Every hand-in is checked independently before its card; one that has not been is moved from the inbox to
``withdrawn``. On 2026-09-27 the promoter picked a hand-in up at 18:19, a minute before it was moved; it kept going
from the files it had read, asked twice at 18:32, both prompts were approved, and a change its check had just found
not safe landed on dev. The promoter now looks for the hand-in in the inbox before each prompt and again before
landing: when it is gone it stops, asks nothing more, lands nothing and writes no verdict, so the hand-in is taken up
again, from the start, only when it is put back.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from scripts.cage import self_change_promoter as sp

from tests.green_support import git, make_blue
from thomas.server import green_checkout, green_handoff
from thomas.tools import cage_shell, trusted_card


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "green-root"))
    repo = make_blue(tmp_path)
    git(repo, "checkout", "-q", "-b", "dev")
    return repo


@pytest.fixture
def pins(tmp_path: Path) -> Path:
    root = tmp_path / "pins"
    root.mkdir()
    (root / trusted_card.PIN_NAME).write_text(trusted_card.catalogue_digest(trusted_card.CATALOGUE_PATH))
    return root


def _submit(blue: Path, execution_id: str) -> Path:
    green = green_checkout.create_green(blue, execution_id)
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    sub = green_handoff.settle(execution_id, promote=True, summary="Fixed it.", chat="chat-1")
    assert sub is not None
    return sub


def _withdraw(sub: Path) -> None:
    held = cage_shell.cage_root() / "withdrawn" / sub.name
    held.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(sub), str(held))


def _unchanged(blue: Path, before: str, sub: Path) -> None:
    outbox = cage_shell.cage_root() / "outbox"
    assert git(blue, "rev-parse", "dev") == before, "nothing landed"
    assert (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (outbox / f"{sub.name}.verdict.json").exists(), "no verdict: it is taken up again when put back"
    assert not (outbox / f"{sub.name}.pending.json").exists(), "and no card left asking"


def test_a_hand_in_withdrawn_before_its_card_is_never_asked(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    sub = _submit(blue, "exec-held-early")
    asked: list[str] = []

    def audit(_repo: Path) -> list[str]:  # runs after the hand-in is read, before any card
        _withdraw(sub)
        return []

    promoter = sp.Promoter(repo=blue, cage_root=cage_shell.cage_root(), ask=lambda a, r: asked.append(a) or True,
                           pin_root=pins, audit=audit)  # fmt: skip
    outcome = promoter.promote(sub)

    assert outcome.status == "withdrawn", outcome.detail
    assert asked == []
    _unchanged(blue, before, sub)


def test_a_hand_in_withdrawn_while_its_card_is_up_does_not_land_on_approval(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    sub = _submit(blue, "exec-held-late")

    def approve_after_it_was_withdrawn(_action: str, _reason: str) -> bool:
        _withdraw(sub)
        return True

    promoter = sp.Promoter(repo=blue, cage_root=cage_shell.cage_root(), ask=approve_after_it_was_withdrawn,
                           pin_root=pins, audit=lambda _repo: [])  # fmt: skip
    outcome = promoter.promote(sub)

    assert outcome.status == "withdrawn", outcome.detail
    _unchanged(blue, before, sub)
