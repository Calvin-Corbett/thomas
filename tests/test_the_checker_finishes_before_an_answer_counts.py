"""Completion and fresh reads, using real checker files in temporary folders; no account or ACL changes (review B2).

From Codex's lineage (work/part4, 2026-10-15), with the undo case written for this lineage's Undoer, whose card is
asked on the loop (Codex's off-loop undo prompt is not taken).
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.cage import card_catalogue
from scripts.cage import checker_completion as cc
from scripts.cage import checker_jobs as cj
from scripts.cage import checker_service as cs
from scripts.cage import self_change_checks as checks
from scripts.cage import window_evidence as we
from scripts.cage import window_review as wr
from scripts.cage.window_checker import CheckerLink
from scripts.cage.window_lane import Lane
from scripts.cage.window_loop import After, WindowLoop
from scripts.cage.window_undo import RETRY_S, Undo, Undoer

from thomas.tools import trusted_card


@pytest.fixture
def link(tmp_path: Path) -> CheckerLink:
    return CheckerLink(tmp_path / "check", clock=lambda: 100.0)


@pytest.fixture
def job(link: CheckerLink) -> cj.Job:
    return link.post(cj.CHECK, base="1" * 40, commit="2" * 40, tree="3" * 40, changed=["thomas/a.py"])


def _answer(job: cj.Job, verdict: str = cj.PASSED, **fields: object) -> cj.Result:
    return cj.Result(
        job.id, job.kind, job.base, job.commit, job.tree, verdict, seen=3, ran=3, finished_at=101.0, **fields
    )


def _raw_answer(link: CheckerLink, job: cj.Job, result: cj.Result) -> None:
    folder = link.root / cj.RESULTS
    folder.mkdir(parents=True, exist_ok=True)
    cj.write_json(cc.result_path(link.root, job), result.to_json())


def test_a_result_alone_does_not_complete_its_job(link: CheckerLink, job: cj.Job) -> None:
    _raw_answer(link, job, _answer(job))
    assert link.result(job) is None
    assert cs.pending_jobs(link.root) == [job]
    cc.publish(link.root, job, _answer(job))
    assert link.result(job) == _answer(job)
    assert cs.pending_jobs(link.root) == []


def test_a_preexisting_pass_is_replaced_with_unavailable_without_running_it(
    link: CheckerLink, job: cj.Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    _raw_answer(link, job, _answer(job))

    def must_not_run(*_args: object, **_kwargs: object) -> cj.Result:
        raise AssertionError("a preexisting answer is an integrity fault")

    monkeypatch.setattr(cs, "run_job", must_not_run)
    result = cs.serve_once(link.root, link.root, python="unused")
    assert result is not None and result.verdict == cj.UNAVAILABLE
    assert "did not write" in result.why
    assert link.result(job) == result
    assert cs.pending_jobs(link.root) == []


def test_the_service_writes_the_answer_before_its_completion_receipt(
    link: CheckerLink, job: cj.Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[Path] = []
    write = cj.write_json

    def observed(path: Path, raw: dict[str, object]) -> None:
        writes.append(path)
        write(path, raw)
        if path == cc.result_path(link.root, job):
            assert link.result(job) is None

    monkeypatch.setattr(cj, "write_json", observed)
    monkeypatch.setattr(cs, "run_job", lambda *_args, **_kwargs: _answer(job))
    result = cs.serve_once(link.root, link.root, python="unused")
    assert writes == [cc.result_path(link.root, job), cc.receipt_path(link.root, job)]
    assert link.result(job) == result == _answer(job)


@pytest.mark.parametrize("damage", ["malformed", "wrong_hash", "missing_result", "replacement"])
def test_damaged_completed_evidence_is_unavailable(link: CheckerLink, job: cj.Job, damage: str) -> None:
    cc.publish(link.root, job, _answer(job))
    if damage == "malformed":
        cc.receipt_path(link.root, job).write_text("{not json", encoding="utf-8")
    elif damage == "wrong_hash":
        raw = cj.read_json(cc.receipt_path(link.root, job))
        cj.write_json(cc.receipt_path(link.root, job), {**raw, "result_sha256": "0" * 64})
    elif damage == "missing_result":
        cc.result_path(link.root, job).unlink()
    else:
        _raw_answer(link, job, _answer(job, cj.FAILED))
    result = link.result(job)
    assert result is not None and result.verdict == cj.UNAVAILABLE
    assert cs.pending_jobs(link.root) == [job]


@pytest.mark.parametrize(
    "changes", [{"changed": ("thomas/b.py",)}, {"tests": ("tests/test_b.py",)}, {"posted_at": 9.0}]
)
def test_completion_binds_the_entire_job(link: CheckerLink, job: cj.Job, changes: dict[str, object]) -> None:
    cc.publish(link.root, job, _answer(job))
    result = link.result(replace(job, **changes))
    assert result is not None and result.verdict == cj.UNAVAILABLE


def test_a_result_replaced_during_the_read_is_unavailable(
    link: CheckerLink, job: cj.Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    cc.publish(link.root, job, _answer(job))
    original, reads = cj.read_json, [0]

    def replaced(path: Path, *args: object) -> object:
        if path == cc.result_path(link.root, job):
            reads[0] += 1
            if reads[0] == 2:
                return _answer(job, cj.FAILED).to_json()
        return original(path, *args)

    monkeypatch.setattr(cj, "read_json", replaced)
    result = link.result(job)
    assert result is not None and result.verdict == cj.UNAVAILABLE


def test_a_fully_republished_different_answer_cannot_replace_a_cached_pass(link: CheckerLink, job: cj.Job) -> None:
    accepted = cc.publish(link.root, job, _answer(job))
    cc.publish(link.root, job, _answer(job, cj.FAILED))
    result = cc.unchanged(job, accepted, link.result)
    assert result.verdict == cj.UNAVAILABLE and "changed" in result.why


def test_cached_evidence_is_retried_if_its_completed_answer_changes(link: CheckerLink, job: cj.Job) -> None:
    cc.publish(link.root, job, _answer(job))
    prep = we.Prep(
        "self-test",
        "4" * 64,
        parent=job.base,
        tree=job.tree,
        change="5" * 64,
        job=job,
        review=wr.Review("5" * 64, wr.SAFE),
    )
    evidence = we.Evidence(link=link, reviewer=object(), clock=lambda: 110.0)
    try:
        assert evidence.gather(SimpleNamespace(), prep) is True
        cc.publish(link.root, job, _answer(job, cj.FAILED))
        assert evidence.gather(SimpleNamespace(), prep) is False
        assert prep.job is None and prep.check is None and prep.retry_at > 110.0
    finally:
        evidence.close()


def test_the_lane_reads_again_at_the_landing_boundary(
    link: CheckerLink, job: cj.Job, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    accepted = cc.publish(link.root, job, _answer(job))
    prep = we.Prep(
        "self-test",
        "4" * 64,
        parent=job.base,
        tree=job.tree,
        change="5" * 64,
        job=job,
        check=accepted,
        review=wr.Review("5" * 64, wr.SAFE),
    )
    promoter = SimpleNamespace(
        repo=tmp_path, branch="dev", _still_in_inbox=lambda: None, audit=lambda _repo: [], _dev=lambda: job.base
    )
    monkeypatch.setattr(checks, "running_copy_refusal", lambda *_args: ("", []))
    lane = Lane(promoter, link=link, reviewer=object(), rules=object(), record=object())
    cc.publish(link.root, job, _answer(job, cj.FAILED))
    try:
        assert lane._land(tmp_path, prep, SimpleNamespace(why_not=lambda: "", opened=object())) is None
        assert prep.check.verdict == cj.UNAVAILABLE and "no longer passes" in prep.wait
    finally:
        lane.close()


def test_the_after_check_is_read_again_before_it_can_allow_another_landing(
    link: CheckerLink, job: cj.Job, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    accepted = cc.publish(link.root, job, _answer(job))
    original = link.result
    calls = [0]

    def swap(asked: cj.Job) -> cj.Result | None:
        calls[0] += 1
        if calls[0] == 1:
            cc.publish(link.root, job, _answer(job, cj.FAILED))
            return accepted
        return original(asked)

    monkeypatch.setattr(link, "result", swap)
    closed: list[str] = []
    events: list[dict[str, object]] = []
    record = SimpleNamespace(event=lambda name, **fields: events.append({"name": name, **fields}))
    window = SimpleNamespace(close=closed.append, take_ended=lambda: [])
    loop = WindowLoop(
        card=object(), lane=object(), undoer=object(), window=window, link=link, record=record, home=tmp_path
    )
    loop.after = After(job, "self-test", job.commit, job.base, 0.0)
    loop._after_check()
    assert calls[0] == 2 and closed
    assert events[0]["name"] == "after_check" and events[0]["verdict"] == cj.UNAVAILABLE


def test_an_undo_answer_replaced_while_its_card_is_open_cannot_land(
    link: CheckerLink, job: cj.Job, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    accepted = cc.publish(link.root, job, _answer(job))
    undo = Undo("self-test", "6" * 40, "revert_change", parent=job.base, tree=job.tree, job=job, check=accepted)
    promoter = SimpleNamespace(repo=tmp_path, branch="dev", _dev=lambda: job.base, audit=lambda _repo: [])
    monkeypatch.setattr(trusted_card, "load_catalogue", lambda: card_catalogue)
    monkeypatch.setattr(checks, "running_copy_refusal", lambda *_args: ("", []))

    def approved(*_args: object) -> tuple[str, str]:
        cc.publish(link.root, job, _answer(job, cj.FAILED))
        return "approved", "ABC-DEF"

    undoer = Undoer(promoter, link=link, record=object(), ask=approved, clock=lambda: 110.0)
    undoer.current = undo
    outcome = undoer._ask_and_land(undo, job.base)
    assert "changed while the card was up" in outcome and "tried again" in outcome
    assert undo.job is None and undo.check is None and undo.retry_at == 110.0 + RETRY_S


def test_pruning_an_expired_answer_removes_only_its_matching_receipt(link: CheckerLink, job: cj.Job) -> None:
    cc.publish(link.root, job, _answer(job))
    other = replace(job, id="a" * 24)
    cc.publish(link.root, other, _answer(other))
    os.utime(cc.result_path(link.root, job), (1.0, 1.0))
    os.utime(cc.result_path(link.root, other), (100.0, 100.0))
    assert cs.prune(link.root, now=150.0, keep_s=100.0) == 1
    assert not cc.result_path(link.root, job).exists() and not cc.receipt_path(link.root, job).exists()
    assert cc.result_path(link.root, other).is_file() and cc.receipt_path(link.root, other).is_file()
