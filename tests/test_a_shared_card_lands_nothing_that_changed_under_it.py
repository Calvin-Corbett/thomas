"""A shared card lands nothing that changed under it: each change is then asked on its own card, and none is refused
for the card.

Your decision, 2026-10-08: "Yes, batch cards". One Windows sign-in can put up to five self-fixes in
(scripts/cage/shared_card.py), and the prompt has no timeout. While it is up, work can appear in the running copy,
``dev`` can move, and the caged account can rewrite any patch in the inbox. Signing in lands every change on the card
or none, and only what the card showed: the running copy is checked again right after your answer, the chain again
before any commit with a plain ``if``, and ``dev`` moves in one compare-and-swap that is put back when the running copy
cannot follow. A card too long for the Windows prompt is never shown, and cards older than this code, or a writer the
audit finds, mean one card at a time, exactly as before.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.cage import card_chain
from scripts.cage import self_change_checks as checks

from tests.green_support import git
from tests.shared_card_support import _submit, blue, shared_card_seed  # noqa: F401
from tests.sleep_support import skip_sleeps
from tests.test_a_self_fix_lands_only_when_you_approve import _outbox, _promoter, pins  # noqa: F401
from tests.test_a_sign_in_windows_did_not_accept_is_asked_again import Answers, _code
from tests.test_one_sign_in_lands_several_self_fixes import _clean
from tests.test_what_is_checked_is_what_lands import _restamp
from thomas.server.self_change_status import RUNNING_COPY_DIRTY
from thomas.tools import cage_shell, trusted_card

CARDS = trusted_card.load_catalogue()
SHARED = CARDS.LIST_KINDS[card_chain.SHARED].title
SINGLE = CARDS.KINDS["promote_batch"].title


class Prompt(Answers):
    """The prompt, answering in turn; ``hooks[n]`` runs while the n-th card (from 0) is up."""

    def __init__(self, *answers: object, hooks: dict | None = None) -> None:
        super().__init__(*answers)
        self.hooks = hooks or {}

    def __call__(self, action: str, reason: str) -> object:
        hook = self.hooks.get(len(self.asked))
        if hook:
            hook()
        return super().__call__(action, reason)


def _two(blue: Path) -> tuple[Path, Path]:
    return _submit(blue, "exec-u-a", {"thomas/a.py": "A = 1\n"}), _submit(blue, "exec-u-b", {"thomas/b.py": "B = 1\n"})


def _titles(ask: Answers) -> list[str]:
    return [action.split("\n", 1)[0] for action, _ in ask.asked]


def _move(blue: Path, text: str) -> None:
    """A commit made in the running copy: dev moves."""
    (blue / "README.md").write_text(text, encoding="utf-8")
    git(blue, "commit", "-qam", text)


def _alone(blue: Path, *subs: Path) -> None:
    """Each landed on its own card: its verdict names no shared card, and no commit says it was on one."""
    for sub in subs:
        verdict = _outbox(sub.name, "verdict")
        assert verdict["status"] == "landed" and verdict["card"] == {}, verdict
        assert "on which this was number" not in git(blue, "log", "-1", "--format=%B", verdict["commit_sha"])


def test_work_that_appears_while_a_shared_card_is_up_is_never_overwritten(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b = _two(blue)
    work = blue / "thomas" / "b.py"
    ask = Prompt("approved", "approved", hooks={0: lambda: work.write_text("WORK = 'yours'\n", encoding="utf-8")})
    promoter = _promoter(blue, pins, ask)

    first = promoter.run_once()

    assert first is not None and first.status == "landed", first
    assert _titles(ask) == [SHARED, SINGLE] and "thomas/a.py" in ask.asked[1][0], "a alone, in the same pass"
    assert git(blue, "rev-list", "--count", f"{before}..dev") == "1", "nothing landed from the card"
    second = promoter.run_once()
    assert second is not None and second.status == "refused", second
    assert second.detail == RUNNING_COPY_DIRTY + "thomas/b.py", "words the server reads to hand it in again"
    assert len(ask.asked) == 2, "refused before any card"
    assert work.read_text(encoding="utf-8") == "WORK = 'yours'\n", "the work is intact"
    assert git(blue, "show", "dev:thomas/a.py") == "A = 1" and _outbox(b.name, "verdict")["status"] == "refused"
    assert [card["state"] for card in _outbox(b.name, "pending")["cards"]] == ["set aside"], "it landed nothing"
    _alone(blue, a)


def test_checking_a_change_on_the_one_ahead_writes_nothing_into_the_running_copy(blue: Path, pins: Path) -> None:
    """Found by these tests: b was checked on top of a with git's three-way apply run in the running copy, and for a
    file both add, git checks out the version it already has (a's) wherever the file is missing (apply.c load_current,
    whatever --cached says). a's file, which you had not approved, was in the running Thomas before any card, and
    stayed after Cancel. Every apply now runs in an empty work tree of its own."""
    _submit(blue, "exec-same-a", {"thomas/same.py": "WHO = 'a'\n"})
    _submit(blue, "exec-same-b", {"thomas/same.py": "WHO = 'b'\n"})
    ask = Answers("cancelled")

    outcome = _promoter(blue, pins, ask).run_once()

    assert outcome is not None and outcome.status == "declined", outcome
    assert _titles(ask) == [SINGLE], "b clashes only with a, so it waits; a is asked alone"
    assert not (blue / "thomas" / "same.py").exists() and _clean(blue), "nothing you did not approve is there"


def test_a_check_never_puts_back_a_file_you_deleted_in_the_running_copy(blue: Path, pins: Path) -> None:
    """The same apply on a single card: dev's version came back over your uncommitted deletion."""
    sub = _submit(blue, "exec-gone", {"thomas/x.py": "X = 1\n"})
    (blue / "thomas" / "x.py").write_text("X = 2\n", encoding="utf-8")
    git(blue, "add", "-A")
    git(blue, "commit", "-qm", "x on dev")
    (blue / "thomas" / "x.py").unlink()

    outcome = _promoter(blue, pins, Answers()).promote(sub)

    assert outcome.status == "refused" and outcome.conflicts == ["thomas/x.py"], outcome
    assert not (blue / "thomas" / "x.py").exists(), "your deletion is intact"


def test_a_dev_that_moved_during_the_shared_card_asks_again_with_a_new_code(blue: Path, pins: Path) -> None:
    a, b = _two(blue)
    ask = Prompt("approved", "approved", hooks={0: lambda: _move(blue, "moved")})

    outcome = _promoter(blue, pins, ask).run_once()

    assert outcome is not None and outcome.status == "landed", outcome
    assert _titles(ask) == [SHARED, SHARED]
    assert _code(ask.asked[0][1]) != _code(ask.asked[1][1]), "a new code for the new dev"
    assert git(blue, "log", "-1", "--format=%s", "dev~2") == "moved", "both landed on the new dev"
    for sub, rev in ((a, "dev~1"), (b, "dev")):
        verdict = _outbox(sub.name, "verdict")
        assert verdict["status"] == "landed" and verdict["commit_sha"] == git(blue, "rev-parse", rev), verdict
        assert verdict["card"]["pairing_code"] == _code(ask.asked[1][1])


def test_dev_moving_three_times_sends_each_change_to_its_own_card(blue: Path, pins: Path) -> None:
    a, b = _two(blue)
    moves = {n: (lambda n=n: _move(blue, f"moved {n}")) for n in range(3)}
    ask = Prompt("approved", "approved", "approved", "approved", "approved", hooks=moves)
    promoter = _promoter(blue, pins, ask)

    assert promoter.run_once().status == "landed"
    assert promoter.run_once().status == "landed"

    assert _titles(ask) == [SHARED, SHARED, SHARED, SINGLE, SINGLE]
    assert len({_code(reason) for _, reason in ask.asked[:3]}) == 3
    assert [card["state"] for card in _outbox(b.name, "pending")["cards"]] == ["set aside"] * 3 + ["approved"]
    _alone(blue, a, b)
    assert git(blue, "log", "-1", "--format=%s", "dev~2") == "moved 2", "nobody refused"


def test_dev_moving_during_the_writer_audit_forms_the_card_again_before_it_is_asked(blue: Path, pins: Path) -> None:
    """The audit can take two minutes. Found in review: a card for the dev before it cost a second sign-in, and a round."""
    _two(blue)

    def audit(_repo: Path) -> list[str]:  # once per shared card: after it forms, before it is asked
        if (blue / "README.md").read_text(encoding="utf-8") != "moved during the audit":
            _move(blue, "moved during the audit")
        return []

    ask = Answers("approved", "approved")
    promoter = _promoter(blue, pins, ask, audit=audit)
    promoter.max_rounds = 1  # the card formed again uses no round

    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]

    assert _titles(ask) == [SHARED], "asked once, about the dev it lands on"
    assert git(blue, "log", "-1", "--format=%s", "dev~2") == "moved during the audit"


def test_a_running_copy_that_cannot_be_updated_asks_each_alone(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b = _two(blue)
    real_land, real_paths = checks.land, checks.run_git_paths
    seen: dict[str, str] = {}

    def checkout_fails(repo: Path, *args: str, paths: list[str]) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("checkout", seen.get("failing")):
            return subprocess.CompletedProcess(["git", *args], 1, "", "error: simulated")
        return real_paths(repo, *args, paths=paths)

    def land(*args: object, **kwargs: object) -> str:
        seen["failing"] = "" if "failing" in seen else str(args[2])  # only the first landing, the shared card's
        try:
            return real_land(*args, **kwargs)
        except checks.Refused:
            seen["dev"] = git(blue, "rev-parse", "dev")
            raise

    monkeypatch.setattr(checks, "run_git_paths", checkout_fails)
    monkeypatch.setattr(checks, "land", land)
    skip_sleeps(monkeypatch)
    ask = Answers("approved", "approved", "approved")
    promoter = _promoter(blue, pins, ask)

    assert promoter.run_once().status == "landed"
    assert promoter.run_once().status == "landed"

    assert seen["dev"] == before, "dev was put back"
    assert _titles(ask) == [SHARED, SINGLE, SINGLE]
    assert git(blue, "rev-list", "--count", f"{before}..dev") == "2"
    _alone(blue, a, b)
    assert _clean(blue), "the running copy holds both, and nothing else"


def test_the_chain_is_checked_again_before_any_commit(blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b = _two(blue)
    real = checks.tree_changes
    lied: list[tuple[str, str]] = []

    def changes_once_differ(repo: Path, parent: str, tree: str) -> list[tuple[str, str]]:
        got = real(repo, parent, tree)
        # member 2's own link, after your answer: what its line was rendered from is not what would be committed
        if ask.asked and not lied and got == [("A", "thomas/b.py")] and parent != before:
            lied.append((parent, tree))
            return [("A", "thomas/other.py")]
        return got

    monkeypatch.setattr(checks, "tree_changes", changes_once_differ)
    ask = Answers("approved", "approved", "approved")
    promoter = _promoter(blue, pins, ask)

    assert promoter.run_once().status == "landed"
    assert promoter.run_once().status == "landed"

    assert lied, "the chain was checked again after the answer"
    assert _titles(ask) == [SHARED, SINGLE, SINGLE], "nothing landed from the card"
    assert git(blue, "rev-list", "--count", f"{before}..dev") == "2"
    _alone(blue, a, b)


def test_a_patch_rewritten_while_a_shared_card_is_built_is_not_what_lands(blue: Path, pins: Path) -> None:
    a, b = _two(blue)

    def audit(_repo: Path) -> list[str]:  # once per shared card: after the chain formed, before it is asked
        _restamp(b, b"thomas/b.py", b"thomas/z.py")
        _restamp(b, b"+B = 1", b"+B = 666")
        return []

    ask = Answers("approved")
    outcome = _promoter(blue, pins, ask, audit=audit).run_once()

    assert outcome is not None and outcome.status == "landed", outcome
    action = ask.asked[0][0]
    assert _titles(ask) == [SHARED] and "thomas/b.py" in action and "thomas/z.py" not in action
    assert git(blue, "show", "dev:thomas/b.py") == "B = 1", "what was checked is what landed"
    assert not (blue / "thomas" / "z.py").exists() and "666" not in (blue / "thomas" / "b.py").read_text()
    assert _outbox(b.name, "verdict")["files"] == ["thomas/b.py"]


def test_a_shared_card_too_long_for_the_prompt_is_never_shown(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = _two(blue)
    built: list[tuple[str, int]] = []
    real = trusted_card.TrustedCard.dialog

    def dialog(card: trusted_card.TrustedCard) -> tuple[str, str]:
        action, reason = real(card)
        built.append((card.kind, len(action) + 2 + len(CARDS.RETRY_NOTE) + 2 + len(reason)))
        return action, reason

    limit = 330  # more than one change's own card, less than the shared card for both
    monkeypatch.setattr(trusted_card.TrustedCard, "dialog", dialog)
    monkeypatch.setattr(CARDS, "DIALOG_LIMIT", limit)
    ask = Answers("approved", "approved")
    promoter = _promoter(blue, pins, ask)

    assert promoter.run_once().status == "landed"
    assert promoter.run_once().status == "landed"

    shared = [size for kind, size in built if kind == card_chain.SHARED]
    assert shared and min(shared) > limit, f"the shared card was made and was too long: {built}"
    assert all(size <= limit for kind, size in built if kind != card_chain.SHARED), built
    assert _titles(ask) == [SINGLE, SINGLE], "never shown cut short"
    _alone(blue, a, b)


def test_cards_older_than_this_code_are_asked_one_at_a_time(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = _two(blue)
    monkeypatch.delattr(CARDS, "LIST_KINDS")
    ask = Answers("approved", "approved")
    promoter = _promoter(blue, pins, ask)

    assert promoter.run_once().status == "landed"
    assert promoter.run_once().status == "landed"

    assert _titles(ask) == [SINGLE, SINGLE]
    _alone(blue, a, b)


def test_a_writer_the_audit_finds_refuses_the_oldest_alone(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    a, b = _two(blue)
    ask = Answers("approved")

    outcome = _promoter(blue, pins, ask, audit=lambda _repo: ["S-1-5-21-9"]).run_once()

    assert outcome is not None and outcome.status == "refused", outcome
    assert outcome.detail == "unexpected writers on Thomas's code: S-1-5-21-9", "today's words"
    assert ask.asked == [] and git(blue, "rev-parse", "dev") == before
    assert _outbox(a.name, "verdict")["status"] == "refused"
    assert b.is_dir() and not (cage_shell.cage_root() / "outbox" / f"{b.name}.verdict.json").exists()
