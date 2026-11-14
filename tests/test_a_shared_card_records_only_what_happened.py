"""Every record a shared card leaves -- each chat's card, each verdict, each commit -- says only what happened.

Your decision, 2026-10-08: "Yes, batch cards". Two reviews of the shared card (scripts/cage/shared_card.py) found
records that said more than happened: a card that landed nothing still said "approved", a commit counted a card you had
cancelled among the cards you approved, and a prompt that broke left every other change's card "asking" while the
oldest change was asked again at once, as it was after a fault right after your approval. Now a card that lands
nothing is "set aside" (design 4.4), a commit counts only the cards you approved, and a fault once the card is up gives
each change on it the error verdict a single card gives for the same fault, with nothing else asked in that pass. A
landing that stops after dev moved gives each change the verdict dev itself supports (design 6.4), and asks nothing
again.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.cage import card_chain
from scripts.cage import self_change_checks as checks
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


def _changes(blue: Path, *names: str) -> list[Path]:
    return [_submit(blue, f"exec-rec-{x}", {f"thomas/{x}.py": f"{x.upper()} = 1\n"}) for x in names]


def _titles(ask: Answers) -> list[str]:
    return [action.split("\n", 1)[0] for action, _ in ask.asked]


def _states(sub: Path) -> list[str]:
    return [card["state"] for card in _outbox(sub.name, "pending")["cards"]]


def test_a_shared_card_that_could_not_land_is_recorded_set_aside(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = _changes(blue, "a", "b")
    real = checks.land
    calls: list[int] = []

    def land(*args: object, **kwargs: object) -> str:
        calls.append(1)
        if len(calls) == 1:  # the shared card's landing: the running copy could not follow, and dev was put back
            raise checks.Refused("the running copy could not be updated (simulated); dev was put back")
        return real(*args, **kwargs)

    monkeypatch.setattr(checks, "land", land)
    promoter = _promoter(blue, pins, Answers("approved", "approved", "approved"))

    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]  # a, alone
    assert _states(b) == ["set aside"], "the card you approved landed nothing"
    assert _states(a) == ["set aside", "approved"]
    prompts_a = _outbox(a.name, "pending")["card_prompts"]
    assert len(prompts_a) == 2, "shared and single card intervals must both survive the retry"
    assert all(item["end"] >= item["start"] > 0 for item in prompts_a)
    assert len(_outbox(b.name, "pending")["card_prompts"]) == 1, "shared interval survives a later pending write"
    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]
    assert _states(b) == ["set aside", "approved"]
    assert _outbox(a.name, "verdict")["card_prompts"] == prompts_a
    assert len(_outbox(b.name, "verdict")["card_prompts"]) == 2


def test_a_change_taken_out_after_you_approved_its_card_keeps_no_approved_card(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dev moved while the card was up, so the card is asked again; c was taken out in between."""
    _a, _b, c = _changes(blue, "a", "b", "c")
    real = sp.Promoter._write

    def write(self: sp.Promoter, kind: str, payload: dict) -> None:
        real(self, kind, payload)
        if kind == "pending" and self._sub_dir.name == c.name and payload["cards"][-1]["state"] == "approved":
            _withdraw(c)

    asked: list[str] = []

    def ask(action: str, _reason: str) -> str:
        if not asked:  # dev moves while the card is up, so the card is asked again after your answer
            (blue / "README.md").write_text("moved", encoding="utf-8")
            git(blue, "commit", "-qam", "moved")
        asked.append(action)
        return "approved"

    monkeypatch.setattr(sp.Promoter, "_write", write)

    assert _promoter(blue, pins, ask).run_once().status == "landed"  # type: ignore[union-attr]

    assert [action.split("\n", 1)[0] for action in asked] == [SHARED, SHARED] and "thomas/c.py" not in asked[1]
    record = cage_shell.cage_root() / "outbox" / f"{c.name}.pending.json"
    assert not record.exists(), f"withdrawn: no card left saying {json.loads(record.read_text())['cards']}"
    assert not (cage_shell.cage_root() / "outbox" / f"{c.name}.verdict.json").exists()


def test_a_commit_counts_only_the_cards_you_approved(blue: Path, pins: Path) -> None:
    a, _b = _changes(blue, "a", "b")
    promoter = _promoter(blue, pins, Answers("cancelled", "approved"))

    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]

    body = git(blue, "log", "-1", "--format=%B", _outbox(a.name, "verdict")["commit_sha"])
    assert "approved by you at the Windows sign-in on 1 card(s)." in body, "never the shared card you cancelled"


def test_a_prompt_that_breaks_gives_each_change_on_the_card_its_error_and_asks_nothing_else(
    blue: Path, pins: Path
) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b = _changes(blue, "a", "b")
    asked: list[str] = []

    def ask(action: str, _reason: str) -> str:
        asked.append(action.split("\n", 1)[0])
        raise ArithmeticError("the prompt broke")  # not a fault the sign-in reads as "not accepted"

    outcome = _promoter(blue, pins, ask).run_once()

    assert outcome is not None and outcome.status == "error", outcome
    assert asked == [SHARED], "nothing else asked in the pass"
    for sub in (a, b):
        verdict = _outbox(sub.name, "verdict")
        assert (verdict["status"], verdict["detail"]) == ("error", "ArithmeticError: the prompt broke"), verdict
        assert _states(sub) == ["interrupted"], "no card left asking"
    assert git(blue, "rev-parse", "dev") == before
    _changes(blue, "c")
    alone = _promoter(blue, pins, ask).run_once()
    assert alone is not None and alone.detail == "ArithmeticError: the prompt broke", "what a single card gives"


def test_a_fault_after_your_approval_gives_each_change_its_error_and_asks_nothing_else(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b = _changes(blue, "a", "b")
    real = checks.running_copy_refusal
    ask = Answers("approved", "approved")
    fired: list[int] = []

    def locked_once(repo: Path, parent: str, tree: str, changes: list[tuple[str, str]]) -> object:
        if ask.asked and not fired:  # right after your answer, outside the landing itself
            fired.append(1)
            raise OSError("simulated: thomas/b.py is locked")
        return real(repo, parent, tree, changes)

    monkeypatch.setattr(checks, "running_copy_refusal", locked_once)

    outcome = _promoter(blue, pins, ask).run_once()

    assert outcome is not None and outcome.status == "error", outcome
    assert _titles(ask) == [SHARED], "the oldest was not asked again straight after your approval"
    for sub in (a, b):
        assert _outbox(sub.name, "verdict")["detail"] == "OSError: simulated: thomas/b.py is locked"
        assert _states(sub) == ["set aside"], "the card landed nothing"
    assert git(blue, "rev-parse", "dev") == before


@pytest.mark.parametrize(("step", "status"), [("checkout", "error"), ("rm", "landed")], ids=["checkout", "after it"])
def test_a_landing_that_stops_after_dev_moved_gives_each_change_its_verdict_and_asks_nothing_again(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch, step: str, status: str
) -> None:
    """PLAN 7.2 said the crash test covered this; it did not. dev moved onto the card, then updating the running copy
    raised: dev holds both changes, and the running copy has them only if the checkout ran."""
    before = git(blue, "rev-parse", "dev")
    a, b = _changes(blue, "a", "b")
    real = checks.run_git_paths
    fired: list[int] = []

    def stops(repo: Path, *args: str, paths: list[str]) -> subprocess.CompletedProcess[str]:
        if args[:1] == (step,) and not fired:
            fired.append(1)
            raise OSError(f"simulated: git {step} could not start")
        return real(repo, *args, paths=paths)

    monkeypatch.setattr(checks, "run_git_paths", stops)
    ask = Answers("approved", "approved", "approved")
    promoter = _promoter(blue, pins, ask)

    assert promoter.run_once().status == status  # type: ignore[union-attr]

    assert promoter.run_once() is None and _titles(ask) == [SHARED], "both decided in that pass; nothing asked again"
    assert git(blue, "rev-list", "--count", f"{before}..dev") == "2", "each landed once"
    for sub, rev in ((a, "dev~1"), (b, "dev")):
        verdict = _outbox(sub.name, "verdict")
        assert verdict["status"] == status and verdict["commit_sha"] == git(blue, "rev-parse", rev), verdict
        assert f"OSError: simulated: git {step} could not start" in verdict["detail"], "it names what happened"
        assert _states(sub) == ["approved"], "you approved it, and dev holds it"
