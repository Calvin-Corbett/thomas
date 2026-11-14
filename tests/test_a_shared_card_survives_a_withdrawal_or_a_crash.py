"""A shared card survives a change taken out of the inbox, and a promoter that stops: nothing lands that was not on
the card as shown, and every change that landed gets its own verdict.

Your decision, 2026-10-08: "Yes, batch cards". The server takes a hand-in out of the inbox to check it again whenever it
must, and the promoter can stop at any moment. A change taken out before its shared card is never asked about, and no
line is dropped from a card, since the lines after it carry its change: the card forms again from what is left. Taken
out while the card is up, nothing on the card lands even on your approval, and the rest are asked alone. Changes that
landed together before the promoter stopped each get "landed" with their own commit, and a card still "asking" when it
stopped says "interrupted", so no chat shows a card nobody is asking.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import card_chain
from scripts.cage import self_change_promoter as sp

from tests.green_support import git
from tests.shared_card_support import _submit, blue, shared_card_seed  # noqa: F401
from tests.test_a_self_fix_lands_only_when_you_approve import _outbox, _promoter, pins  # noqa: F401
from tests.test_a_sign_in_windows_did_not_accept_is_asked_again import Answers
from tests.test_a_withdrawn_hand_in_is_never_asked import _withdraw
from thomas.tools import cage_shell, trusted_card

CARDS = trusted_card.load_catalogue()
SHARED = CARDS.LIST_KINDS[card_chain.SHARED].title
SINGLE = CARDS.KINDS["promote_batch"].title


def _three(blue: Path) -> list[Path]:
    return [_submit(blue, f"exec-w-{x}", {f"thomas/{x}.py": f"{x.upper()} = 1\n"}) for x in "abc"]


def _titles(asked: list[tuple[str, str]]) -> list[str]:
    return [action.split("\n", 1)[0] for action, _ in asked]


def _record(sub: Path, kind: str) -> Path:
    return cage_shell.cage_root() / "outbox" / f"{sub.name}.{kind}.json"


def _never_decided(sub: Path) -> None:
    """Withdrawn: no verdict and no card left asking, so it is taken up again from the start once it is back."""
    assert not _record(sub, "verdict").exists() and not _record(sub, "pending").exists()


def test_a_member_taken_out_before_the_card_is_never_asked_and_nothing_it_held_lands(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b, c = _three(blue)

    def audit(_repo: Path) -> list[str]:  # once per shared card: after its chain formed, before it is asked
        if a.is_dir():
            _withdraw(a)
        return []

    ask = Answers("approved")
    promoter = _promoter(blue, pins, ask, audit=audit)

    outcome = promoter.run_once()

    assert outcome is not None and outcome.status == "withdrawn", outcome
    assert ask.asked == [] and git(blue, "rev-parse", "dev") == before, "no card asked; nothing landed"
    _never_decided(a)
    assert not _record(b, "pending").exists() and not _record(c, "pending").exists(), "no card shown for the rest"
    assert promoter.run_once().status == "landed"
    assert _titles(ask.asked) == [SHARED] and "thomas/a.py" not in ask.asked[0][0], "a new chain, from what is left"
    assert git(blue, "rev-list", "--count", f"{before}..dev") == "2" and not (blue / "thomas" / "a.py").exists()
    assert git(blue, "ls-tree", "-r", "--name-only", "dev", "thomas").split() == [
        "thomas/b.py",
        "thomas/c.py",
        "thomas/fix_me.py",
    ], "the lines after a never carried its change"
    _never_decided(a)


def test_a_member_taken_out_while_the_card_is_up_lands_nothing_and_the_rest_go_alone(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b, c = _three(blue)
    asked: list[tuple[str, str]] = []

    def ask(action: str, reason: str) -> str:
        asked.append((action, reason))
        if len(asked) == 1:
            _withdraw(b)
        return "approved"

    promoter = _promoter(blue, pins, ask)

    first = promoter.run_once()

    assert first is not None and first.status == "landed", first
    assert _titles(asked) == [SHARED, SINGLE] and "thomas/a.py" in asked[1][0], "a alone, at once"
    assert git(blue, "rev-list", "--count", f"{before}..dev") == "1", "nothing landed from the card"
    _never_decided(b)
    assert promoter.run_once().status == "landed"
    assert _titles(asked) == [SHARED, SINGLE, SINGLE] and "thomas/c.py" in asked[2][0], "c alone, next pass"
    assert promoter.run_once() is None
    for sub in (a, c):
        assert _outbox(sub.name, "verdict")["card"] == {}, "neither shared again"
    _never_decided(b)


def test_a_member_taken_out_between_failed_sign_ins_is_not_shown_again(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b, c = _three(blue)
    asked: list[str] = []

    def ask(action: str, _reason: str) -> str:
        asked.append(action)
        if len(asked) == 1:
            _withdraw(b)
            return "failed"
        return "approved"

    promoter = _promoter(blue, pins, ask)

    assert promoter.run_once().status == "landed"
    assert promoter.run_once().status == "landed"

    assert _titles([(x, "") for x in asked]) == [SHARED, SINGLE, SINGLE], "the shared card was asked once"
    assert "thomas/a.py" in asked[1] and "thomas/c.py" in asked[2]
    assert git(blue, "rev-list", "--count", f"{before}..dev") == "2"
    _never_decided(b)


@pytest.mark.parametrize("stops_at", [1, 2], ids=["before any verdict", "after the first verdict"])
def test_changes_that_landed_together_before_a_crash_get_landed_verdicts(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch, stops_at: int
) -> None:
    """One edits a file dev has; the other deletes one and adds a changelog fragment, as most self-fixes do."""
    (blue / "thomas" / "old.py").write_text("OLD = 1\n", encoding="utf-8")
    git(blue, "add", "-A")
    git(blue, "commit", "-qm", "a file b deletes")
    a = _submit(blue, "exec-crash-a", {"thomas/fix_me.py": "VALUE = 2\n"})
    b = _submit(blue, "exec-crash-b", {"thomas/old.py": None, "changelog.d/b.md": "### Fixed\n\n- b\n"})
    assert b is not None
    real = sp.Promoter._finish
    calls: list[str] = []

    def stop(self: sp.Promoter, sub: Path, outcome: sp.Outcome) -> None:
        calls.append(sub.name)
        if len(calls) == stops_at:
            raise SystemExit("the promoter stopped")
        real(self, sub, outcome)

    with monkeypatch.context() as patched:
        patched.setattr(sp.Promoter, "_finish", stop)
        with pytest.raises(SystemExit):
            _promoter(blue, pins, Answers("approved")).run_once()
    assert calls[0] == a.name and b.is_dir(), "dev moved; b's verdict was never written"
    ask = Answers()
    fresh = _promoter(blue, pins, ask)

    assert fresh.run_once().status == "landed"
    assert fresh.run_once() is None and ask.asked == [], "nothing asked again"

    recovered = [a, b] if stops_at == 1 else [b]
    for sub, rev in ((a, "dev~1"), (b, "dev")):
        verdict = _outbox(sub.name, "verdict")
        assert verdict["status"] == "landed" and verdict["commit_sha"] == git(blue, "rev-parse", rev), verdict
        written_now = verdict["detail"] == "landed before the promoter stopped; its verdict is written now"
        assert written_now is (sub in recovered), verdict
        assert not sub.exists()
    if stops_at == 2:
        assert _outbox(a.name, "verdict")["card"]["position"] == 1, "written before the stop, naming its card"


def test_a_stale_asking_card_is_marked_interrupted_at_start(blue: Path, pins: Path) -> None:
    a = _submit(blue, "exec-stale-a", {"thomas/a.py": "A = 1\n"})
    b = _submit(blue, "exec-stale-b", {"thomas/b.py": "B = 1\n"})
    outbox = cage_shell.cage_root() / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    cards = {"cards": [{"state": "set aside"}, {"state": "asking"}]}
    _record(a, "pending").write_text(json.dumps(cards), encoding="utf-8")
    _record(b, "pending").write_text("not json", encoding="utf-8")
    promoter = _promoter(blue, pins, Answers())
    promoter.clock = lambda: 0.0
    promoter._quiet_until = 10.0  # every hand-in waits: nothing is asked, and the sweep still runs

    assert promoter.run_once().status == "held"

    states = [card["state"] for card in json.loads(_record(a, "pending").read_text(encoding="utf-8"))["cards"]]
    assert states == ["set aside", "interrupted"]
    assert _record(b, "pending").read_text(encoding="utf-8") == "not json", "unreadable: left as it is"
    _record(a, "pending").write_text(json.dumps(cards), encoding="utf-8")  # asked by this promoter, after its start
    assert promoter.run_once().status == "held"
    assert "asking" in _record(a, "pending").read_text(encoding="utf-8"), "once per process"


def test_a_stale_asking_card_of_a_hand_in_put_back_later_is_marked_interrupted(blue: Path, pins: Path) -> None:
    """Found in review: a hand-in out of the inbox when the promoter started, and put back later, kept a card "asking"
    that nobody was asking. Each hand-in is looked at the first time this promoter sees it."""
    a = _submit(blue, "exec-later-a", {"thomas/a.py": "A = 1\n"})
    _submit(blue, "exec-later-b", {"thomas/b.py": "B = 1\n"})
    _record(a, "pending").parent.mkdir(parents=True, exist_ok=True)
    _record(a, "pending").write_text(json.dumps({"cards": [{"state": "asking"}]}), encoding="utf-8")
    _withdraw(a)  # taken out to be checked while the old promoter was down
    promoter = _promoter(blue, pins, Answers())
    promoter.clock = lambda: 0.0
    promoter._quiet_until = 10.0  # every hand-in waits: nothing is asked, and the sweep still runs

    assert promoter.run_once().status == "held"
    (cage_shell.cage_root() / "withdrawn" / a.name).rename(a)  # put back
    assert promoter.run_once().status == "held"

    states = [card["state"] for card in json.loads(_record(a, "pending").read_text(encoding="utf-8"))["cards"]]
    assert states == ["interrupted"], "no chat shows a card nobody is asking"
