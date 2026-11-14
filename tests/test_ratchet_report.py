"""What the page and Chat read -- the census, the ledger and the halt -- and the lease that keeps one run at a time."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ratchet_support import dev_moves, extra_candidate, make_repo
from thomas.server import green_handoff
from thomas.server.ratchet.candidates import discover, write_census
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.lease import lease
from thomas.server.ratchet.ledger import Ledger
from thomas.server.ratchet.report import read_report
from thomas.tools import cage_shell


def test_every_candidate_is_listed_with_its_state_and_reason(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    folder = tmp_path / "ratchet"
    write_census(folder, discover(Repo(repo)))
    book = Ledger(folder / "ledger.jsonl")

    first = read_report(folder)
    dev = first["dev_sha"]
    book.record(sha=sha, refs=["refs/heads/fix/extra"], dev_sha=dev, state="reported", reason="1 new failure(s): x")
    book.record(sha="e" * 40, refs=["refs/heads/gone"], dev_sha=dev, state="landed", reason="landed as 1234")
    later = read_report(folder)

    rows = [(row["ref"], row["state"], row["reason"]) for row in first["candidates"]]
    assert rows == [("refs/heads/fix/extra", "queued", "not proven yet")]
    assert later["counts"] == {"reported": 1, "landed": 1}
    assert later["candidates"][1]["ref"] == "refs/heads/gone"  # one the census no longer sees still shows
    assert later["halted"] == {}


def test_report_reflects_a_withdrawn_hand_in_without_changing_other_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path / "cage"))
    folder = tmp_path / "ratchet"
    book = Ledger(folder / "ledger.jsonl")
    sid = "self-ratchet-report"
    inbox = green_handoff.inbox_dir()
    (inbox / sid).mkdir(parents=True)
    book.record(sha="a" * 40, refs=["refs/heads/fix/x"], dev_sha="b" * 40,
                state="awaiting_card", reason="waiting for your card", submission=sid)  # fmt: skip
    assert read_report(folder)["candidates"][0]["reason"] == "waiting for your card"

    withdrawn = inbox.parent / "withdrawn"
    withdrawn.mkdir()
    (inbox / sid).rename(withdrawn / sid)
    row = read_report(folder)["candidates"][0]
    assert row["state"] == "queued"
    assert "you were never asked" in row["reason"]
    assert read_report(folder)["counts"] == {"queued": 1}

    outbox = cage_shell.cage_root() / "outbox"
    outbox.mkdir()
    (outbox / f"{sid}.verdict.json").write_text('{"status": "declined", "detail": "you declined it"}', encoding="utf-8")
    assert read_report(folder)["candidates"][0]["state"] == "awaiting_card"


def test_a_halt_is_in_the_report(tmp_path: Path) -> None:
    folder = tmp_path / "ratchet"
    reason = "1234 broke tests/test_x.py::test_x"
    Ledger(folder / "ledger.jsonl").halt(commit="1" * 40, reason=reason, failures=["tests/test_x.py::test_x"])

    assert read_report(folder)["halted"]["reason"] == reason


def test_one_run_at_a_time(tmp_path: Path) -> None:
    with lease(tmp_path) as first:
        with lease(tmp_path) as second:
            assert first is True and second is False
    with lease(tmp_path) as again:
        assert again is True
