"""Real failure confirmation creates one observable baseline and cleans both copies."""

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from thomas.server.precard import check, clocks
from thomas.server.precard.lint import LintResult
from thomas.server.proof import Selection, runner


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    green = check.green_checkout.Green("lazy-base", tmp_path / "green", tmp_path / "git", "base", tmp_path / "blue")
    base = SimpleNamespace(work=tmp_path / "baseline")
    change = SimpleNamespace(work=tmp_path / "changed")
    calls, removed, reruns = [], [], []
    test_id = "tests/test_value.py::test_value"

    def make(_blue, _tip, _eid, part):
        calls.append(part)
        copy = base if part == check.scratch.BASE else change
        copy.work.mkdir()
        return copy

    def discard(*copies):
        for copy in copies:
            if copy is not None:
                removed.append(copy)
                shutil.rmtree(copy.work)

    def run_one(work, test, **kwargs):
        assert test == test_id
        reruns.append(work)
        return runner.FAILED if work == change.work else runner.PASSED

    monkeypatch.setattr(check.scratch, "copy_of_dev", make)
    monkeypatch.setattr(check.scratch, "discard_all", discard)
    monkeypatch.setattr(check.scratch, "apply_change", lambda *_: "")
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_: [])
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: Selection(("tests/test_value.py",), ()))
    monkeypatch.setattr(check.proofs, "run_tests", lambda *_a, **_k: runner.ProofRun(True, "", (test_id,), 1, 1))
    monkeypatch.setattr(check.proofs, "run_one", run_one)
    monkeypatch.setattr(check.known, "key", lambda *_: "key")
    monkeypatch.setattr(check.known, "read", lambda *_: frozenset())
    monkeypatch.setattr(check.known, "remember", lambda *_: None)
    monkeypatch.setattr(check.lint, "ruff_findings", lambda *_a, **_k: LintResult(True, "", (), ()))
    return SimpleNamespace(
        green=green,
        base=base,
        change=change,
        calls=calls,
        removed=removed,
        reruns=reruns,
        make=make,
        catalog=tmp_path,
    )


def run(pipeline):
    return check._against_dev(
        pipeline.green,
        "tip",
        "patch",
        ["pkg/value.py"],
        "python",
        False,
    )


def test_real_failure_makes_one_baseline_and_cleans_both_copies(pipeline):
    with clocks.recording(pipeline.catalog, "real-lazy-copy") as record:
        result = run(pipeline)
    assert result.state == check.FAILED, result
    assert pipeline.calls == [check.scratch.WITH_CHANGE, check.scratch.BASE]
    assert pipeline.reruns == [pipeline.change.work, pipeline.base.work]
    assert record["stages"]["base_copy"]["seconds"] >= 0
    assert pipeline.removed == [pipeline.base, pipeline.change]
    assert not pipeline.base.work.exists()
    assert not pipeline.change.work.exists()


@pytest.mark.parametrize(
    "error",
    [
        check.green_checkout.GreenUnavailable("cannot clone baseline"),
        subprocess.TimeoutExpired("git clone", 1),
    ],
)
def test_real_baseline_copy_failure_is_held_and_changed_copy_is_removed(pipeline, monkeypatch, error):
    def make(blue, tip, eid, part):
        if part == check.scratch.BASE:
            pipeline.calls.append(part)
            raise error
        return pipeline.make(blue, tip, eid, part)

    monkeypatch.setattr(check.scratch, "copy_of_dev", make)
    with clocks.recording(pipeline.catalog, "failed-lazy-copy") as record:
        result = run(pipeline)
    assert result.state == check.UNAVAILABLE
    assert result.cause == "incomplete"
    assert result.costly
    assert pipeline.calls == [check.scratch.WITH_CHANGE, check.scratch.BASE]
    assert "base_copy" in record["stages"]
    assert pipeline.removed == [pipeline.change]
    assert not pipeline.change.work.exists()
    assert not pipeline.base.work.exists()
