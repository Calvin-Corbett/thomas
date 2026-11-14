"""Every candidate's history, one JSON line per event, and the rule for proving one again.

Dev moves about 46 commits a day (2026-09-24), so a candidate that landed, is on
dev already, is not for the ratchet, or that you declined is never proven again
for the same commit; a report is proven again only on a new dev, and only so often.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.ratchet_support import candidate
from thomas.server import green_handoff
from thomas.server.ratchet import ledger as ledger_module
from thomas.server.ratchet.ledger import DECLINED, MAX_REPORTS, Ledger, ratchet_root
from thomas.tools import cage_shell

A, B = "a" * 40, "b" * 40
CAND = candidate("c" * 40, "refs/heads/fix/x")


def _book(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "ledger.jsonl")


def test_a_new_candidate_is_proven_and_a_landed_one_never_again(tmp_path: Path) -> None:
    book = _book(tmp_path)
    assert book.should_prove(CAND.sha, A) == (True, "")

    event = book.record(candidate=CAND, dev_sha=A, state="landed", reason="landed as 1234", landed_commit="1" * 40)

    assert event["candidate_ref"] == "refs/heads/fix/x" and event["refs"] == ["refs/heads/fix/x"]
    prove, why = book.should_prove(CAND.sha, B)
    assert not prove and why.startswith("landed")


def test_a_report_is_proven_again_only_on_a_new_dev_and_only_so_often(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.record(candidate=CAND, dev_sha=A, state="reported", reason="1 new failure(s)")

    assert book.should_prove(CAND.sha, A)[0] is False
    assert book.should_prove(CAND.sha, B)[0] is True
    for n in range(MAX_REPORTS - 1):
        book.record(candidate=CAND, dev_sha=str(n) * 40, state="reported", reason="again")
    prove, why = book.should_prove(CAND.sha, "f" * 40)
    assert not prove and f"reported {MAX_REPORTS} times" in why


def test_your_decline_holds_until_the_candidate_changes(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.record(candidate=CAND, dev_sha=A, state="reported", reason=f"{DECLINED}: you declined the change")

    assert book.should_prove(CAND.sha, B)[0] is False
    assert book.should_prove("d" * 40, B)[0] is True


def test_waiting_and_interrupted_attempts(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.record(candidate=CAND, dev_sha=A, state="awaiting_card", reason="waiting for your card", submission="self-x")
    assert book.should_prove(CAND.sha, B) == (False, "waiting for your card")
    assert [e["submission"] for e in book.awaiting()] == ["self-x"]

    book.record(candidate=CAND, dev_sha=A, state="queued", reason="waiting: the running copy has work in x")
    assert book.should_prove(CAND.sha, A)[0] is True
    book.record(candidate=CAND, dev_sha=A, state="proving", reason="proving it on dev")
    assert book.should_prove(CAND.sha, A)[0] is True  # a restart cut it short
    book.record(candidate=CAND, dev_sha=A, state="settling", reason="handing it to the promoter", submission="self-y")
    assert book.should_prove(CAND.sha, B)[0] is False  # the next run asks the promoter's folders first


def test_a_withdrawn_card_is_not_described_as_waiting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path / "cage"))
    book = _book(tmp_path)
    sid = "self-withdrawn-ledger"
    book.record(candidate=CAND, dev_sha=A, state="awaiting_card", reason="waiting for your card", submission=sid)
    inbox = green_handoff.inbox_dir()
    (inbox / sid).mkdir(parents=True)
    withdrawn = inbox.parent / "withdrawn"
    withdrawn.mkdir(exist_ok=True)
    (inbox / sid).rename(withdrawn / sid)

    assert book.should_prove(CAND.sha, B) == (
        False,
        "the hand-in was withdrawn before your card; you were never asked; the next run proves it again",
    )


def test_a_candidate_that_will_never_be_proven_again_says_why(tmp_path: Path) -> None:
    book = _book(tmp_path)
    assert book.gave_up(CAND.sha) == ""

    book.record(candidate=CAND, dev_sha=A, state="reported", reason=f"{DECLINED}: you declined the change")
    book.record(sha="d" * 40, refs=["refs/heads/d"], dev_sha=A, state="not_for_ratchet", reason="public history")

    assert book.gave_up(CAND.sha).startswith(DECLINED)
    assert book.gave_up("d" * 40) == "not for the ratchet: public history"


def test_a_halt_stops_until_it_is_cleared_and_is_kept_afterwards(tmp_path: Path) -> None:
    book = _book(tmp_path)
    assert book.halted() is None

    book.halt(commit="1" * 40, reason="it broke a test", failures=["tests/test_x.py::test_x"], missing=[])
    assert book.halted()["failures"] == ["tests/test_x.py::test_x"]
    book.clear_halt("every test it named passes on dev")

    assert book.halted() is None
    [kept] = tmp_path.glob("halt-cleared-*.json")
    assert json.loads(kept.read_text(encoding="utf-8"))["cleared"] == "every test it named passes on dev"
    (tmp_path / "halt.json").write_text("{not json", encoding="utf-8")
    assert "cannot be read" in book.halted()["reason"]  # a damaged halt still stops every run


def test_a_half_written_line_is_skipped_and_an_unknown_state_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    book = Ledger(path)
    book.record(candidate=CAND, dev_sha=A, state="queued", reason="x")
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"candidate_sha": "')

    book.record(candidate=CAND, dev_sha=A, state="queued", reason="y")

    assert [e["reason"] for e in book.events()] == ["x", "y"]
    with pytest.raises(ValueError):
        book.record(candidate=CAND, dev_sha=A, state="merged")


def test_the_ledger_lives_where_the_environment_says(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ledger_module.ROOT_ENV, str(tmp_path / "r"))

    assert ratchet_root() == tmp_path / "r"
    assert Ledger().path == tmp_path / "r" / "ledger.jsonl"
