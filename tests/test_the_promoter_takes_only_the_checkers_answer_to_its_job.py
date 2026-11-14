"""The promoter posts a job to the checker and takes only an answer for exactly that job (spec section 8.2, 1-2).

Its own tmp folder stands in for C:\\ProgramData\\ThomasCheck; no checker process runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.cage import checker_completion as cc
from scripts.cage import checker_jobs as cj
from scripts.cage.window_checker import CheckerLink

BASE, COMMIT, TREE = "1" * 40, "2" * 40, "3" * 40


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def link(tmp_path: Path) -> CheckerLink:
    return CheckerLink(tmp_path / "check", clock=Clock())


def _answer(link: CheckerLink, job: cj.Job, **over: object) -> None:
    fields = {"verdict": cj.PASSED, "finished_at": 1.0, "ran": 1, "seen": 1}  # a pass that tested nothing is none (B3)
    fields.update(over)
    result = cj.Result(job.id, job.kind, job.base, job.commit, job.tree, **fields)  # type: ignore[arg-type]
    cc.publish(link.root, job, result)  # the answer and its completion receipt, as the checker writes them (B2)


def test_a_posted_job_is_what_the_checker_reads(link: CheckerLink) -> None:
    job = link.post(cj.CHECK, base=BASE, commit=COMMIT, tree=TREE, changed=["thomas/fix_me.py"])
    assert cj.Job.parse(cj.read_json(link.root / cj.JOBS / f"{job.id}.json")) == job
    assert link.post(cj.CHECK, base=BASE, commit=COMMIT, tree=TREE, changed=[]).id != job.id


def test_no_answer_yet_is_none_and_an_answer_for_the_job_is_taken(link: CheckerLink) -> None:
    job = link.post(cj.CHECK, base=BASE, commit=COMMIT, tree=TREE, changed=["thomas/fix_me.py"])
    assert link.result(job) is None
    _answer(link, job)
    found = link.result(job)
    assert found is not None and found.verdict == cj.PASSED


def test_an_answer_for_another_tree_is_unavailable_never_passed(link: CheckerLink) -> None:
    job = link.post(cj.CHECK, base=BASE, commit=COMMIT, tree=TREE, changed=[])
    forged = cj.Job(job.id, job.kind, job.base, job.commit, "4" * 40, job.changed)
    _answer(link, forged)
    found = link.result(job)
    assert found is not None and found.verdict == cj.UNAVAILABLE and "another job" in found.why


def test_a_garbled_answer_is_unavailable(link: CheckerLink) -> None:
    job = link.post(cj.CHECK, base=BASE, commit=COMMIT, tree=TREE, changed=[])
    (link.root / cj.RESULTS).mkdir(parents=True, exist_ok=True)
    (link.root / cj.RESULTS / f"{job.id}.json").write_text('{"verdict": "PASSED"}', encoding="utf-8")
    found = link.result(job)
    assert found is not None and found.verdict == cj.UNAVAILABLE


def test_the_checker_counts_only_while_it_beats_and_is_fenced(link: CheckerLink) -> None:
    state = link.root / cj.STATE
    assert "not running" in link.answering()
    state.mkdir(parents=True)
    (state / cj.HEARTBEAT).write_text("990.0", encoding="utf-8")
    assert "fenced" in link.answering()
    cj.write_json(state / cj.FENCE, {"fenced": True, "detail": "", "checked_at": 990.0})
    assert link.answering() == ""
    link.clock.now = 2000.0  # type: ignore[attr-defined]
    assert "has not beaten" in link.answering()


def test_a_job_is_removed_once_its_answer_is_taken(link: CheckerLink) -> None:
    job = link.post(cj.CHECK, base=BASE, commit=COMMIT, tree=TREE, changed=[])
    link.forget(job)
    assert not (link.root / cj.JOBS / f"{job.id}.json").exists()
