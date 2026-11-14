"""The ratchet's run: one landing at a time, only in the caged Thomas, and halted by a landing that broke a test."""

from __future__ import annotations

import asyncio
import getpass
import itertools
import sys
from pathlib import Path

import pytest

from tests.ratchet_support import (
    FakeCage,
    dev_moves,
    extra_candidate,
    git,
    make_repo,
    orphan,
    promote,
    submissions,
    verdict,
)
from thomas.server import green_checkout
from thomas.server.ratchet.attempt import Hooks
from thomas.server.ratchet.ledger import Ledger
from thomas.server.ratchet.report import read_report
from thomas.server.ratchet.service import (
    ACCOUNT_ENV,
    DEV_MOVED_RETRIES,
    RatchetService,
    autorun_enabled,
    host_refusal,
)


@pytest.fixture
def here(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ACCOUNT_ENV, getpass.getuser())


def _hooks(cage: FakeCage | None = None, **overrides: object) -> Hooks:
    return Hooks(run_caged=cage or FakeCage(), runner_alive=lambda: True, dirty_wait_s=0.0, **overrides)


def _states(root: Path, sha: str) -> list[str]:
    return [e["state"] for e in Ledger(root / "ledger.jsonl").events() if e["candidate_sha"] == sha]


def test_a_run_proves_the_backlog_and_lands_it_by_your_card(tmp_path: Path, here: None) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)

    async def the_promoter(_seconds: float) -> None:  # your card, answered while the ratchet waits
        [sub] = submissions()
        verdict(sub, "landed", commit=promote(repo, sub), files=["tests/test_extra.py", "thomas/core/extra.py"])

    service = RatchetService(repo=repo, root=tmp_path / "ratchet", hooks=_hooks(sleep=the_promoter, poll_s=0.0))

    outcome = asyncio.run(service.run_once(limit=3))

    assert outcome == {"status": "ran", "proven": [{"ref": "refs/heads/fix/extra", "sha": sha, "state": "landed"}]}
    report = read_report(tmp_path / "ratchet")
    assert report["counts"] == {"landed": 1}
    assert report["candidates"][0]["state"] == "landed"


def test_a_card_still_waiting_holds_back_every_new_submission(tmp_path: Path, here: None) -> None:
    repo = make_repo(tmp_path)
    extra_candidate(repo)
    dev_moves(repo)
    Ledger(tmp_path / "ratchet" / "ledger.jsonl").record(
        sha="e" * 40,
        refs=["refs/heads/earlier"],
        dev_sha="d" * 40,
        state="awaiting_card",
        reason="waiting for your card",
        submission="self-ratchet-cand-eeeeeee-ddddddd",
        files=[],
    )
    service = RatchetService(repo=repo, root=tmp_path / "ratchet", hooks=_hooks(verdict_timeout_s=0.0))

    assert asyncio.run(service.run_once()) == {"status": "awaiting_card", "candidate": "refs/heads/earlier"}
    assert submissions() == []


def test_a_halt_stops_every_run_until_the_tests_it_names_pass_on_dev(tmp_path: Path, here: None) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    root = tmp_path / "ratchet"
    reason = "1234 landed and broke tests/test_widget.py::test_widget"
    Ledger(root / "ledger.jsonl").halt(commit="1" * 40, reason=reason, failures=["tests/test_widget.py::test_widget"])
    still_broken = FakeCage({"halt": {"tests/test_widget.py"}})

    assert asyncio.run(RatchetService(repo=repo, root=root, hooks=_hooks(still_broken)).run_once()) == {
        "status": "halted",
        "reason": reason,
    }
    assert submissions() == [] and _states(root, sha) == []

    fixed = RatchetService(repo=repo, root=root, hooks=_hooks(verdict_timeout_s=0.0))
    assert asyncio.run(fixed.run_once())["status"] == "ran"
    assert Ledger(root / "ledger.jsonl").halted() is None
    assert _states(root, sha)[-1] == "awaiting_card"


def test_a_dev_that_moves_during_the_proof_is_proven_again_on_the_new_tip(tmp_path: Path, here: None) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    moved: list[str] = []

    def once(label: str) -> None:
        if label == "cand" and not moved:
            moved.append(dev_moves(repo, "someone landed"))

    root = tmp_path / "ratchet"
    service = RatchetService(repo=repo, root=root, hooks=_hooks(FakeCage(during=once), verdict_timeout_s=0.0))

    outcome = asyncio.run(service.run_once())

    assert outcome["proven"] == [{"ref": "refs/heads/fix/extra", "sha": sha, "state": "awaiting_card"}]
    assert _states(root, sha) == ["proving", "queued", "proving", "settling", "awaiting_card"]
    assert Ledger(root / "ledger.jsonl").latest()[sha]["dev_sha"] == moved[0]


def test_a_dev_that_never_stops_moving_leaves_the_candidate_queued(tmp_path: Path, here: None) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    count = itertools.count()
    cage = FakeCage(during=lambda label: dev_moves(repo, f"move {next(count)}") if label == "cand" else None)
    root = tmp_path / "ratchet"

    outcome = asyncio.run(RatchetService(repo=repo, root=root, hooks=_hooks(cage)).run_once())

    assert outcome["proven"] == [{"ref": "refs/heads/fix/extra", "sha": sha, "state": "queued"}]
    assert _states(root, sha) == ["proving", "queued"] * (DEV_MOVED_RETRIES + 1)


def test_the_run_refuses_outside_the_caged_thomas_or_without_the_cage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    monkeypatch.setenv(ACCOUNT_ENV, "somebody-else")
    outcome = asyncio.run(RatchetService(repo=repo, root=tmp_path / "r", hooks=_hooks()).run_once())
    assert outcome["status"] == "refused" and "caged Thomas" in outcome["reason"]

    monkeypatch.setenv(ACCOUNT_ENV, getpass.getuser())
    down = Hooks(run_caged=FakeCage(), runner_alive=lambda: False)
    outcome = asyncio.run(RatchetService(repo=repo, root=tmp_path / "r", hooks=down).run_once())
    assert "caged runner is not answering" in outcome["reason"]


def test_a_copy_without_the_promoters_checks_is_refused_whatever_its_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """A release carries the package and not ``scripts/cage``, so its code loads and a run must not get as far as them."""
    monkeypatch.setenv(ACCOUNT_ENV, getpass.getuser())
    assert host_refusal() == ""

    monkeypatch.setitem(sys.modules, "scripts.cage", None)  # what importing it in a release comes to
    assert "this install has none of the checks a run needs" in host_refusal()


def test_what_is_not_for_the_ratchet_is_recorded_once(tmp_path: Path, here: None) -> None:
    repo = make_repo(tmp_path)
    orphan(repo, "refs/remotes/origin/main", {"README.md": "public\n"}, "public")
    dev_moves(repo)
    service = RatchetService(repo=repo, root=tmp_path / "ratchet", hooks=_hooks())

    asyncio.run(service.run_once())
    asyncio.run(service.run_once())

    assert [e["state"] for e in Ledger(tmp_path / "ratchet" / "ledger.jsonl").events()] == ["not_for_ratchet"]


def test_git_or_a_green_failing_is_a_wait_not_a_report_against_the_candidate(
    tmp_path: Path, here: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAX_REPORTS is for a candidate's own failures. A run in scratch phase 2 reported one three times for
    "git checkout failed: ... Filename too long", which is this machine's trouble, not the candidate's."""
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    root = tmp_path / "ratchet"

    def no_green(blue: Path, execution_id: str) -> None:
        raise green_checkout.GreenUnavailable("git checkout failed: Filename too long")

    monkeypatch.setattr(green_checkout, "create_green", no_green)

    outcome = asyncio.run(RatchetService(repo=repo, root=root, hooks=_hooks()).run_once())

    assert outcome["proven"] == [{"ref": "refs/heads/fix/extra", "sha": sha, "state": "queued"}]
    book = Ledger(root / "ledger.jsonl")
    assert book.reports(sha) == 0
    assert "the attempt could not run here" in book.latest()[sha]["reason"]
    assert submissions() == []


def test_a_repair_whose_green_is_gone_is_proven_again_rather_than_left_behind(tmp_path: Path, here: None) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    root = tmp_path / "ratchet"
    Ledger(root / "ledger.jsonl").record(
        sha=sha,
        refs=["refs/heads/fix/extra"],
        dev_sha=git(repo, "rev-parse", "dev"),
        state="repairing",
        reason="a Build team is repairing it",
        execution_id="ratchet-cand-0000000-0000000",
        conversation_id="conv-gone",
    )
    service = RatchetService(repo=repo, root=root, hooks=_hooks(verdict_timeout_s=0.0))

    outcome = asyncio.run(service.run_once())

    assert outcome["status"] == "ran"
    states = _states(root, sha)
    assert states[:2] == ["repairing", "queued"] and states[-1] == "awaiting_card"
    assert "the green it was in is gone" in Ledger(root / "ledger.jsonl").events()[1]["reason"]


def test_tests_never_start_the_daily_run() -> None:
    """Autorun is on unless the environment says otherwise, so conftest sets it off rather than
    defaulting it off: a run inheriting THOMAS_RATCHET_AUTORUN=1 from a Thomas server's shell would
    otherwise prove real backlog candidates in real greens while the suite ran."""
    assert autorun_enabled() is False
