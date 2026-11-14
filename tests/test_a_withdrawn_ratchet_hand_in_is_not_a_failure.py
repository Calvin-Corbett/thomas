"""A withdrawn hand-in is a wait, not a judgment on its candidate."""

from __future__ import annotations

import asyncio
import getpass
from pathlib import Path

import pytest

from tests.ratchet_support import FakeCage, candidate, dev_moves, extra_candidate, make_repo, submissions, verdict
from thomas.server import green_handoff
from thomas.server.ratchet import landing
from thomas.server.ratchet.attempt import Context, Hooks, prove_candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import DECLINED, Ledger
from thomas.server.ratchet.service import ACCOUNT_ENV, RatchetService
from thomas.tools import cage_shell

WITHDRAWN = "the hand-in was withdrawn before your card; you were never asked"


@pytest.fixture(autouse=True)
def own_inbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path / "cage"))


def _hooks() -> Hooks:
    return Hooks(run_caged=FakeCage(), runner_alive=lambda: True, dirty_wait_s=0.0, verdict_timeout_s=0.0)


def _withdraw(sub: Path) -> Path:
    withdrawn = green_handoff.inbox_dir().parent / "withdrawn"
    withdrawn.mkdir(exist_ok=True)
    target = withdrawn / sub.name
    sub.rename(target)
    return target


def test_a_withdrawn_proven_hand_in_waits_without_reporting(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev = dev_moves(repo)
    book = Ledger(tmp_path / "ratchet" / "ledger.jsonl")
    ctx = Context(repo=Repo(repo), ledger=book, hooks=_hooks())
    assert asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/fix/extra"))) == "awaiting_card"
    [sub] = submissions()
    _withdraw(sub)

    assert asyncio.run(landing.await_landing(ctx, book.latest()[sha])) == "queued"
    last = book.latest()[sha]
    assert (last["state"], last["reason"], last["submission"]) == ("queued", WITHDRAWN, sub.name)
    assert last["dev_sha"] == dev
    assert book.reports(sha) == 0
    assert book.gave_up(sha) == ""
    assert book.should_prove(sha, dev) == (True, "")


def test_reconcile_queues_a_withdrawn_settling_hand_in(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha, dev = "c" * 40, "d" * 40
    execution = "ratchet-cand-ccccccc-ddddddd"
    sid = f"self-{execution}"
    book = Ledger(tmp_path / "ratchet" / "ledger.jsonl")
    book.record(sha=sha, refs=["refs/heads/fix/extra"], dev_sha=dev, state="settling",
                execution_id=execution, submission=sid)  # fmt: skip
    sub = green_handoff.inbox_dir() / sid
    sub.mkdir(parents=True)
    _withdraw(sub)

    landing.reconcile(Context(repo=Repo(repo), ledger=book, hooks=_hooks()))

    last = book.latest()[sha]
    assert (last["state"], last["reason"], last["submission"]) == ("queued", WITHDRAWN, sid)
    assert book.reports(sha) == 0
    assert book.should_prove(sha, dev) == (True, "")


def test_three_withdrawals_retry_on_same_dev_with_distinct_names_but_a_decline_stops_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ACCOUNT_ENV, getpass.getuser())
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev = dev_moves(repo)
    book = Ledger(tmp_path / "ratchet" / "ledger.jsonl")
    service = RatchetService(repo=repo, root=tmp_path / "ratchet", hooks=_hooks())
    expected = [{"ref": "refs/heads/fix/extra", "sha": sha, "state": "awaiting_card"}]
    assert asyncio.run(service.run_once())["proven"] == expected

    withdrawn_names: list[str] = []
    for _ in range(3):
        [sub] = submissions()
        withdrawn_names.append(_withdraw(sub).name)
        assert asyncio.run(service.run_once())["proven"] == expected
        withdrawals = [row for row in book.events() if row["candidate_sha"] == sha and row["reason"] == WITHDRAWN]
        assert len(withdrawals) == len(withdrawn_names)
        assert all(row["state"] == "queued" for row in withdrawals)
        assert book.reports(sha) == 0
        assert book.gave_up(sha) == ""
        assert book.should_prove(sha, dev) == (False, "waiting for your card")
        [current] = submissions()
        assert current.name not in withdrawn_names
        assert current.name == book.latest()[sha]["submission"]

    assert landing.submissions_from(withdrawn_names[0].removeprefix("self-")) == [withdrawn_names[0]]
    [sub] = submissions()
    verdict(sub, "declined", detail="you declined the change")
    assert asyncio.run(service.run_once())["proven"] == []
    reason = f"{DECLINED}: you declined the change"
    assert book.latest()[sha]["reason"] == reason
    assert book.reports(sha) == 1
    assert book.gave_up(sha) == reason
    assert book.should_prove(sha, dev_moves(repo, "after decline")) == (
        False,
        "you declined it; it is proposed again only if it changes",
    )


def test_three_declines_still_count_as_reports_and_stop_proving(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    book = Ledger(tmp_path / "ratchet" / "ledger.jsonl")
    reason = f"{DECLINED}: no"
    for count in range(1, 4):
        book.record(sha=sha, dev_sha=dev_moves(repo, f"dev {count}"), state="reported", reason=reason)
        assert book.reports(sha) == count
        assert book.gave_up(sha) == reason
    assert book.should_prove(sha, dev_moves(repo, "fourth")) == (
        False,
        "you declined it; it is proposed again only if it changes",
    )
