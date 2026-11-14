"""The proof cap is checked before a repair Build is spent on a candidate, and on every green before a test runs.

The unify candidate 2f730c5 spent 3 repair Builds, 5.1 hours, before the proof's 300-file cap reported it (measured
2026-10-07): the proof set was only chosen after the repair. Here the cap is lowered so the fixture's few tests pass
it. A candidate that needs a repair is counted on the merge first, by what its repair is asked to keep; one that
needs none is refused on its green before dev's proof or its own runs. A wait still costs only a screen.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.ratchet_support import FakeCage, candidate, dev_moves, extra_candidate, git, make_repo, on_ref, submissions
from thomas.server import green_checkout
from thomas.server.precard import review
from thomas.server.ratchet import attempt, proof_set, screen
from thomas.server.ratchet.attempt import Context, Hooks, prove_candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import MAX_REPORTS, Ledger
from thomas.server.ratchet.proof_need import FOUND_EARLY, past_the_cap, proof_need
from thomas.server.ratchet.results import SideResult, capped, compare

EXTRA_TEST = "from thomas.core import extra\n\n\ndef test_extra():\n    assert extra.X\n"


class _Repairs:
    """A server that can start repair runs: records each one it is asked for."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def repair(self, ctx: Context, att: Any, *, verdict: Any) -> str:
        self.calls.append(att.candidate.sha)
        return "repairing"

    async def resume(self, ctx: Context, att: Any, cid: str) -> str:
        raise AssertionError("no repair is resumed here")


class _Card:
    """The second look and the hand-off to your card: records each, in order, and approves nothing."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []

    def settle(self, execution_id: str, **_: Any) -> Path | None:
        self.log.append(("hand-off", execution_id))
        return None  # nothing is submitted, so nothing can be approved

    def second_look(self, execution_id: str, request: str, checked: Any) -> Any:
        self.log.append(("second look", execution_id))
        return checked


def _ctx(repo: Path, tmp_path: Path, cage: FakeCage, card: _Card, repairs: _Repairs | None = None) -> Context:
    hooks = Hooks(run_caged=cage, runner_alive=lambda: True, dirty_wait_s=0.0, settle=card.settle)
    ledger = Ledger(tmp_path / "ratchet" / "ledger.jsonl")
    return Context(repo=Repo(repo), ledger=ledger, hooks=hooks, repairs=repairs)


def _no_green_was_made() -> bool:
    work = green_checkout.green_root() / "work"
    return not work.is_dir() or not list(work.iterdir())


@pytest.fixture
def card(monkeypatch: pytest.MonkeyPatch) -> _Card:
    found = _Card()
    monkeypatch.setattr(review, "second_look", found.second_look)
    return found


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every early count the attempt asks for."""
    calls: list[str] = []
    real = attempt.capped_before_a_repair

    def spy(repo: Repo, dev_sha: str, cand: Any, found: Any, **kwargs: Any) -> str:
        calls.append(cand.sha)
        return real(repo, dev_sha, cand, found, **kwargs)

    monkeypatch.setattr(attempt, "capped_before_a_repair", spy)
    return calls


def _clashing(repo: Path, extra: dict[str, str]) -> str:
    """A candidate that changes widget.py, which dev has since changed its own way, and *extra* cleanly."""
    base = git(repo, "rev-parse", "dev")
    sha = on_ref(repo, "refs/heads/clash", base, {"thomas/core/widget.py": "VALUE = 3\n", **extra}, "clash")
    dev_moves(repo, "dev fixes it", {"thomas/core/widget.py": "VALUE = 2\n"})
    return sha


def test_a_candidate_whose_own_changes_pass_the_cap_is_reported_before_a_repair_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, card: _Card, counted: list[str]
) -> None:
    repo = make_repo(tmp_path)
    clash = _clashing(repo, {"thomas/core/extra.py": "X = 1\n", "tests/test_extra.py": EXTRA_TEST})
    monkeypatch.setattr(proof_set, "MAX_FILES", 1)  # the architecture test's place, and nothing else
    cage, repairs = FakeCage(), _Repairs()
    ctx = _ctx(repo, tmp_path, cage, card, repairs)

    state = asyncio.run(prove_candidate(ctx, candidate(clash, "refs/heads/clash")))

    event = ctx.ledger.latest()[clash]
    assert state == "reported" and counted == [clash], event
    assert event["reason"] == (  # its own test and test_widget.py: widget.py, which both sides changed, is counted
        "2 test file(s) that prove it would not be run, not counting what its repair is told to keep as dev has it: "
        "the proof set is capped at 1. " + FOUND_EARLY
    )
    assert repairs.calls == [], "no repair Build was started for a candidate the cap would refuse"
    assert cage.calls == [] and cage.ended == [] and _no_green_was_made(), "and no green was made for it"
    assert card.log == [] and submissions() == [], "nothing reached a second look or your card"
    assert [e["state"] for e in ctx.ledger.events()] == ["proving", "reported"]


def test_a_file_its_repair_is_told_to_keep_as_dev_has_it_is_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, card: _Card, counted: list[str]
) -> None:
    """Review 2026-10-07, R4: counted with old.py and its test, which dev deleted and the candidate changed, the
    merge reaches one test file past the cap. Its repair is told to keep dev's deletions, so neither is counted --
    the test is read as gone, though the candidate's copy names extra.py -- and it goes on to its repair."""
    repo = make_repo(tmp_path)
    names = 'TARGET = "thomas.core.old.OLD"\n\n\ndef test_names():\n    assert TARGET\n'  # a patch() target
    base = dev_moves(repo, "a test names old.py", {"tests/test_names.py": names})
    files = {"thomas/core/old.py": "OLD = 3\n", "thomas/core/extra.py": "X = 1\n", "tests/test_extra.py": EXTRA_TEST,
             "tests/test_names.py": names.replace("thomas.core.old.OLD", "thomas.core.extra.X")}  # fmt: skip
    sha = on_ref(repo, "refs/heads/old", base, files, "old and extra")
    dev = dev_moves(repo, "dev retires old.py", {"thomas/core/old.py": None, "tests/test_names.py": None})
    monkeypatch.setattr(proof_set, "MAX_FILES", 2)
    found = screen.screen(Repo(repo), dev, candidate(sha))
    kinds = [(c.path, c.kind) for c in found.conflicts]
    assert kinds == [("tests/test_names.py", "dev_deleted"), ("thomas/core/old.py", "dev_deleted")], kinds
    whole = proof_need(Repo(repo), dev, candidate(sha), [path for _status, path in found.changes])
    assert whole.left_out == 1, "the whole merge is over the cap"
    repairs = _Repairs()

    state = asyncio.run(prove_candidate(_ctx(repo, tmp_path, FakeCage(), card, repairs), candidate(sha)))

    assert state == "repairing" and repairs.calls == [sha] and counted == [sha]


def test_a_file_both_sides_changed_is_counted_because_its_repair_keeps_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, card: _Card, counted: list[str]
) -> None:
    """Review 2026-10-07, R4's other half, kept on purpose: widget.py, which both sides changed, is counted. A repair
    that kept only dev's widget.py would have come in under; leaving such files out lets the unify candidate past
    its count (1,403 test files left out with them, 0 without; measured 2026-10-07). A report fails closed."""
    repo = make_repo(tmp_path)
    clash = _clashing(repo, {"thomas/core/extra.py": "X = 1\n", "tests/test_extra.py": EXTRA_TEST})
    monkeypatch.setattr(proof_set, "MAX_FILES", 2)
    repairs = _Repairs()
    ctx = _ctx(repo, tmp_path, FakeCage(), card, repairs)

    state = asyncio.run(prove_candidate(ctx, candidate(clash, "refs/heads/clash")))

    assert state == "reported" and repairs.calls == [] and counted == [clash]
    assert FOUND_EARLY in ctx.ledger.latest()[clash]["reason"] and ctx.ledger.reports(clash) == 1


def test_a_candidate_that_waits_for_a_repair_server_pays_no_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, card: _Card, counted: list[str]
) -> None:
    """A wait costs a screen, not a proof set (ledger.py): it is queued as before, and is not used up as a report."""
    repo = make_repo(tmp_path)
    clash = _clashing(repo, {"thomas/core/extra.py": "X = 1\n", "tests/test_extra.py": EXTRA_TEST})
    monkeypatch.setattr(proof_set, "MAX_FILES", 1)
    ctx = _ctx(repo, tmp_path, FakeCage(), card, repairs=None)

    state = asyncio.run(prove_candidate(ctx, candidate(clash, "refs/heads/clash")))

    assert state == "queued" and counted == [] and ctx.ledger.reports(clash) == 0
    assert "it needs a repair run" in ctx.ledger.latest()[clash]["reason"]


def test_a_clean_candidate_past_the_cap_is_refused_on_its_green_before_any_proof_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, card: _Card, counted: list[str]
) -> None:
    """No repair Build is at stake, so no early count: its green's own selection refuses it before dev's proof,
    the boot check or its own proof is run."""
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    monkeypatch.setattr(proof_set, "MAX_FILES", 1)
    cage = FakeCage()
    ctx = _ctx(repo, tmp_path, cage, card, _Repairs())

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"

    assert counted == [], "a clean candidate is not counted twice"
    assert (
        ctx.ledger.latest()[sha]["reason"]
        == capped(1)
        == ("1 test file(s) that prove it were not run: the proof set is capped at 1")
    )
    assert cage.calls == [] and cage.labels == [] and card.log == [], "no test ran and nothing reached your card"


def test_a_candidate_under_the_cap_goes_on_to_its_proof_its_second_look_and_your_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, card: _Card
) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    monkeypatch.setenv(review.REVIEW_ENV, "on")  # the second look runs (its reader is stubbed)
    cage = FakeCage()
    ctx = _ctx(repo, tmp_path, cage, card, _Repairs())

    state = asyncio.run(prove_candidate(ctx, candidate(sha)))

    assert state == "reported", "the stubbed hand-off submits nothing, and says so"
    assert set(cage.labels) == {"base", "cand"}, "proven as before"
    [(first, green), (then, same)] = card.log
    assert (first, then) == ("second look", "hand-off") and green == same, "the second look is not skipped"
    reason = ctx.ledger.latest()[sha]["reason"]
    assert FOUND_EARLY not in reason and reason == "the hand-off to the promoter failed, so nothing was submitted"


def test_the_early_count_is_the_count_the_proof_makes_on_the_same_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, card: _Card
) -> None:
    """The two checks cannot disagree: the same selection, on the same tree, with the same limit."""
    repo = make_repo(tmp_path)
    start = git(repo, "rev-parse", "dev")
    more = "from thomas.core import widget\n\n\ndef test_more():\n    assert widget.VALUE\n"
    files = {"thomas/core/widget.py": "VALUE = 5\n", "tests/test_more.py": more, "README.md": "blue: and docs\n"}
    sha = on_ref(repo, "refs/heads/more", start, files, "widget and a test")
    dev_moves(repo, "dev moves", {"thomas/core/old.py": "OLD = 2\n"})
    dev = git(repo, "rev-parse", "dev")
    seen: list[tuple[proof_set.ProofSet, proof_set.ProofSet]] = []
    chosen = attempt.select

    def spy(green: Repo, tree: str, changed: list[str], **kwargs: Any) -> proof_set.ProofSet:
        picked = chosen(green, tree, changed, **kwargs)
        seen.append((picked, chosen(green, tree, changed, base=kwargs.get("base", ""), limit=2)))
        return picked

    monkeypatch.setattr(attempt, "select", spy)
    ctx = _ctx(repo, tmp_path, FakeCage(), card, _Repairs())
    found = screen.screen(Repo(repo), dev, candidate(sha))
    early = proof_need(Repo(repo), dev, candidate(sha), [path for _status, path in found.changes])

    asyncio.run(prove_candidate(ctx, candidate(sha)))

    [(late, late_capped)] = seen
    assert early == late and sorted(early.files) == [
        "tests/test_architecture.py",
        "tests/test_more.py",
        "tests/test_widget.py",
    ]
    monkeypatch.setattr(proof_set, "MAX_FILES", 2)
    assert proof_need(Repo(repo), dev, candidate(sha), [p for _s, p in found.changes]) == late_capped
    assert late_capped.left_out == 1


def test_the_early_reason_says_what_the_late_check_says_and_what_happens_next() -> None:
    ran = SideResult(("tests/test_a.py",), passing={"tests/test_a.py::test_a": "test_a"}, ran=1)
    late = compare(ran, ran, left_out=4).reason
    early = past_the_cap(proof_set.ProofSet(("tests/test_a.py",), left_out=4))

    assert late.split(": ", 1)[1] == early.split(": ", 1)[1].split(". ")[0], (late, early)
    assert early.startswith("4 test file(s) that prove it would not be run") and early.endswith(FOUND_EARLY)
    assert f"until it has been reported {MAX_REPORTS} times" in FOUND_EARLY and "split" not in early
    assert past_the_cap(proof_set.ProofSet(("tests/test_a.py",), left_out=0)) == ""


def test_a_stacked_candidate_is_counted_as_its_own_commit_above_the_work_that_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot above work that landed under another commit is proven as its own commit on top of it
    (``apply_candidate`` with ``pick``), so its count comes from that merge, not from the whole line."""
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    lower_test = "from thomas.core import extra\n\n\ndef test_lower():\n    assert extra.X\n"
    lower_files = {"thomas/core/extra.py": "X = 1\n", "tests/test_lower.py": lower_test}
    lower = on_ref(repo, "refs/heads/fix/lower", base, lower_files, "lower")
    snap = on_ref(repo, "refs/salvage/run/snap", lower, {"thomas/core/extra.py": "X = 2\n"}, "snapshot")
    dev_moves(repo, "the lower work lands under its own commit", lower_files)
    dev = dev_moves(repo, "dev retires the lower test", {"tests/test_lower.py": None})
    monkeypatch.setattr(proof_set, "MAX_FILES", 1)

    need = proof_need(Repo(repo), dev, candidate(snap, stacked_on=lower), ["thomas/core/extra.py"], onto=lower)

    assert need.left_out == 0 and "tests/test_lower.py" not in need.files, need
