"""What your card decided, confirmed in git before anything is called landed.

The promoter re-derives a change on whatever dev is when it picks the submission
up, and a per-file card you decline leaves that file out while the rest lands
(self_change_promoter.py:133-186). "Landed" is recorded only after git agrees.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.ratchet_support import (
    FakeCage,
    candidate,
    dev_moves,
    extra_candidate,
    git,
    make_repo,
    promote,
    submissions,
    verdict,
)
from thomas.server import green_handoff
from thomas.server.ratchet import landing
from thomas.server.ratchet.archive import archive_refs
from thomas.server.ratchet.attempt import Context, Hooks, prove_candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import DECLINED, Ledger
from thomas.tools import cage_shell

FILES = ["tests/test_extra.py", "thomas/core/extra.py"]


def _proven(tmp_path: Path, cage: FakeCage | None = None, **hooks: float) -> tuple[Path, str, Context]:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    git(repo, "update-ref", "refs/salvage/run/same", sha)
    dev_moves(repo)
    ctx = Context(
        repo=Repo(repo),
        ledger=Ledger(tmp_path / "ratchet" / "ledger.jsonl"),
        hooks=Hooks(run_caged=cage or FakeCage(), runner_alive=lambda: True, dirty_wait_s=0.0, **hooks),
    )
    cand = candidate(sha, "refs/heads/fix/extra", "refs/salvage/run/same")
    assert asyncio.run(prove_candidate(ctx, cand)) == "awaiting_card"
    return repo, sha, ctx


def _decide(ctx: Context, sha: str) -> str:
    return asyncio.run(landing.await_landing(ctx, ctx.ledger.latest()[sha]))


def test_your_card_lands_it_and_its_refs_are_archived_without_being_deleted(tmp_path: Path) -> None:
    repo, sha, ctx = _proven(tmp_path)
    [sub] = submissions()
    landed = promote(repo, sub)
    verdict(sub, "landed", commit=landed, files=FILES)

    assert _decide(ctx, sha) == "landed"
    event = ctx.ledger.latest()[sha]
    assert event["landed_commit"] == landed and "on the dev its proof ran on" in event["reason"]
    archived = git(repo, "for-each-ref", "--format=%(refname)", "refs/archive/ratchet").splitlines()
    assert archived == ["refs/archive/ratchet/heads/fix/extra", "refs/archive/ratchet/salvage/run/same"]
    # You asked that the ratchet never delete a branch: both refs still point where they did.
    kept = git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/fix", "refs/salvage").splitlines()
    assert kept == ["refs/heads/fix/extra", "refs/salvage/run/same"]
    assert git(repo, "rev-parse", "refs/heads/fix/extra") == sha
    assert ctx.ledger.should_prove(sha, dev_moves(repo, "later"))[0] is False  # landed: never proven again


def test_a_card_you_decline_is_recorded_and_not_asked_again(tmp_path: Path) -> None:
    repo, sha, ctx = _proven(tmp_path)
    [sub] = submissions()
    verdict(sub, "declined", detail="you declined the change")

    assert _decide(ctx, sha) == "reported"
    assert ctx.ledger.latest()[sha]["reason"] == f"{DECLINED}: you declined the change"
    assert ctx.ledger.should_prove(sha, dev_moves(repo, "later"))[0] is False


def test_a_refusal_is_recorded_in_the_promoters_words(tmp_path: Path) -> None:
    _repo, sha, ctx = _proven(tmp_path)
    [sub] = submissions()
    verdict(sub, "refused", detail="the running copy has uncommitted work in thomas/core/extra.py")

    assert _decide(ctx, sha) == "reported"
    assert ctx.ledger.latest()[sha]["reason"] == (
        "the promoter refused it: the running copy has uncommitted work in thomas/core/extra.py"
    )


def test_a_landing_git_does_not_confirm_is_not_called_landed(tmp_path: Path) -> None:
    repo, sha, ctx = _proven(tmp_path)
    [sub] = submissions()
    verdict(sub, "landed", commit=promote(repo, sub, trailer=False), files=FILES)

    assert _decide(ctx, sha) == "reported"
    assert "carries submission none" in ctx.ledger.latest()[sha]["reason"]


def test_a_landing_on_a_moved_dev_is_proven_again_as_it_landed(tmp_path: Path) -> None:
    cage = FakeCage()
    repo, sha, ctx = _proven(tmp_path, cage)
    [sub] = submissions()
    dev_moves(repo, "another agent landed first")
    verdict(sub, "landed", commit=promote(repo, sub), files=FILES)

    assert _decide(ctx, sha) == "landed"
    event = ctx.ledger.latest()[sha]
    assert "not the dev its proof ran on" in event["reason"] and event["after_landing"]["ok"] is True
    assert {"prnt", "land"} <= set(cage.labels)
    assert {"prnt", "land"} <= {green.split("-")[1] for green in cage.ended}  # both proof greens are ended


def test_a_landing_that_breaks_a_test_halts_every_run_and_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = []
    monkeypatch.setattr(landing, "record_issue", lambda **kw: issues.append(kw))
    repo, sha, ctx = _proven(tmp_path, FakeCage({"land": {"tests/test_extra.py"}}))
    [sub] = submissions()
    dev_moves(repo, "another agent landed first")
    verdict(sub, "landed", commit=promote(repo, sub), files=FILES)

    assert _decide(ctx, sha) == "halted"
    assert ctx.ledger.latest()[sha]["state"] == "landed"
    assert issues and issues[0]["kind"] == "landed_regression"
    halt = ctx.ledger.halted()
    assert halt["failures"] == ["tests/test_extra.py::test_extra"] and halt["candidate_sha"] == sha


def test_a_hand_off_a_restart_cut_short_is_found_again(tmp_path: Path) -> None:
    book = Ledger(tmp_path / "ratchet" / "ledger.jsonl")
    ctx = Context(repo=Repo(make_repo(tmp_path)), ledger=book, hooks=Hooks(run_caged=FakeCage()))
    written, lost = "a" * 40, "b" * 40
    for sha in (written, lost):
        sid = f"self-ratchet-cand-{sha[:7]}-ddddddd"
        book.record(sha=sha, refs=[f"refs/heads/{sha[:1]}"], dev_sha="d" * 40, state="settling", submission=sid)
    (green_handoff.inbox_dir() / f"self-ratchet-cand-{written[:7]}-ddddddd").mkdir(parents=True)

    landing.reconcile(ctx)

    assert book.latest()[written]["state"] == "awaiting_card"
    assert book.latest()[written]["submission"] == f"self-ratchet-cand-{written[:7]}-ddddddd"
    assert book.latest()[lost]["state"] == "queued"


def test_a_hand_off_is_found_by_its_green_even_when_it_was_not_named_self_execution_id(tmp_path: Path) -> None:
    """A green that has handed in before names its next hand-in ``-2`` (green_handoff._next_id), and a
    repair green is kept for its verdict, so the name recorded before the hand-off can be the wrong one.
    Matched by name, this change -- already on your card -- would go back to queued and be handed in twice."""
    book = Ledger(tmp_path / "ratchet" / "ledger.jsonl")
    ctx = Context(repo=Repo(make_repo(tmp_path)), ledger=book, hooks=Hooks(run_caged=FakeCage()))
    sha, execution = "c" * 40, "ratchet-cand-ccccccc-ddddddd"
    book.record(
        sha=sha,
        refs=["refs/heads/fix/repaired"],
        dev_sha="d" * 40,
        state="settling",
        submission=f"self-{execution}",  # what the run guessed before the hand-off
        execution_id=execution,
        files=["thomas/core/extra.py"],
    )
    (green_handoff.inbox_dir() / f"self-{execution}-2").mkdir(parents=True)  # what it was actually called

    landing.reconcile(ctx)

    found = book.latest()[sha]
    assert found["state"] == "awaiting_card"
    assert found["submission"] == f"self-{execution}-2"
    assert found["files"] == ["thomas/core/extra.py"]


def test_a_green_that_never_handed_in_is_not_matched_by_another_greens_submission(tmp_path: Path) -> None:
    book = Ledger(tmp_path / "ratchet" / "ledger.jsonl")
    ctx = Context(repo=Repo(make_repo(tmp_path)), ledger=book, hooks=Hooks(run_caged=FakeCage()))
    execution = "ratchet-cand-eeeeeee-ddddddd"
    book.record(sha="e" * 40, refs=[], dev_sha="d" * 40, state="settling", execution_id=execution)
    (green_handoff.inbox_dir() / "self-ratchet-cand-fffffff-ddddddd").mkdir(parents=True)

    landing.reconcile(ctx)

    assert book.latest()["e" * 40]["state"] == "queued"
    assert landing.submissions_from(execution) == []


def test_withdrawn_hand_in_is_queued_without_a_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path / "cage"))
    _repo, sha, ctx = _proven(tmp_path)
    [sub] = submissions()
    inbox = green_handoff.inbox_dir()
    withdrawn = inbox.parent / "withdrawn"
    withdrawn.mkdir()
    sub.rename(withdrawn / sub.name)

    assert _decide(ctx, sha) == "queued"
    assert ctx.ledger.latest()[sha]["state"] == "queued"
    assert "you were never asked" in ctx.ledger.latest()[sha]["reason"]
    assert landing.submission_exists(sub.name)


def test_no_verdict_in_time_leaves_it_waiting(tmp_path: Path) -> None:
    _repo, sha, ctx = _proven(tmp_path, verdict_timeout_s=0.0)

    assert _decide(ctx, sha) == "awaiting_card"


def test_the_archive_copies_only_local_refs_and_never_overwrites(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    git(repo, "update-ref", "refs/remotes/dev-origin/extra", sha)
    git(repo, "update-ref", "refs/archive/ratchet/heads/fix/extra", sha)
    git(repo, "update-ref", "refs/salvage/run/same", sha)

    refs = ["refs/heads/fix/extra", "refs/salvage/run/same", "refs/remotes/dev-origin/extra", "refs/heads/dev"]
    notes = archive_refs(Repo(repo), refs, sha)

    assert notes["refs/heads/fix/extra"].startswith("kept: refs/archive/ratchet/heads/fix/extra could not be written")
    assert notes["refs/salvage/run/same"] == "copied to refs/archive/ratchet/salvage/run/same"
    assert notes["refs/remotes/dev-origin/extra"] == "kept: not a local ref"
    assert notes["refs/heads/dev"] == "kept: it is dev"
    assert git(repo, "rev-parse", "refs/heads/fix/extra") == sha
    assert git(repo, "rev-parse", "refs/salvage/run/same") == sha  # copied, not moved
