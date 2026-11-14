"""A shard the pool refused holds the check back, but never hides what was proven without it.

Failures the started shards found are re-run on their own on both copies, and ruff and the size rule read the files
themselves: none of that depends on the shard that never started. So a regression proven alone, a lint finding or a size
problem still sends the change back to its team. What does depend on the incomplete full runs (a failure nobody could
settle, a re-run that timed out, a run that broke) must not send it back, and the check is held for another try
(``busy``, no strike). Sibling of ``test_a_shard_that_did_not_finish_proves_and_measures_nothing.py``.

Dev is run in full only when the change's run leaves the answer to it (spec 2026-10-12 Part 1 item 3), so the cases
where dev's shard is refused make the change's run not finish. A re-run on its own the pool gave no place is the same as
a refused shard: it proved nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_checks_share_one_machine_wide_pool import GIB, _quiet_steps, _steps_args
from thomas.server import precard
from thomas.server.precard import check, pool, report
from thomas.server.precard.lint import LintResult
from thomas.server.proof import FAILED, PASSED, TIMEOUT, UNKNOWN, ProofRun, runner

REGRESSION = "tests/test_ok.py::test_regressed"
NO_PLACE = "the pool's reservation ledger could not be used, so the shard did not start: stayed locked"
CLEAN = LintResult(True, "", (), ())
RUFF = "pkg/adder.py:3:1: F401 `os` imported but unused"
SIZE = "pkg/adder.py is 900 lines, over the 800-line limit"

# (what the failed test does re-run on its own with the change, then on dev), ruff, the size rule, and the answer
FAILS = {
    "a regression proven alone": (FAILED, PASSED, CLEAN, [], REGRESSION),
    "a lint finding": (PASSED, PASSED, LintResult(True, "", (RUFF,), ()), [], RUFF),
    "a size problem": (PASSED, PASSED, CLEAN, [SIZE], SIZE),
}
HELD = {
    "a flaky test (fails in the full run, passes alone)": (PASSED, PASSED),
    "a failure nobody could settle": (UNKNOWN, PASSED),
    "a re-run that timed out": (TIMEOUT, PASSED),
}


def _check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str, alone: tuple[str, str], lint: LintResult,
    size: list[str], run_trouble: str = "",
) -> precard.Checked:  # fmt: skip
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    _quiet_steps(monkeypatch)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * GIB, 20 * GIB))
    monkeypatch.setattr(check.lint, "ruff_findings", lambda *_a, **_k: lint)
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_a: size)

    def fake_tests(work: Path, files: tuple, **_kwargs: object) -> ProofRun:
        failed = (REGRESSION,) if work.name == "change" else ()
        if refused == work.name:
            why = run_trouble + NO_PLACE
            return ProofRun(False, why, failed, 1, 2, not_started=("tests/test_ok.py",), not_started_why=NO_PLACE)
        if refused == "base":  # dev runs in full only when the change's run leaves it to dev: here, it did not finish
            return ProofRun(False, "tests/test_other.py: pytest exited 2: boom", failed, 1, 2)
        return ProofRun(True, "", failed, 2, 2)

    monkeypatch.setattr(check.proofs, "run_tests", fake_tests)
    monkeypatch.setattr(
        check.proofs, "run_one", lambda work, test, **_k: alone[0] if work.name == "change" else alone[1]
    )
    return check._steps(*_steps_args(tmp_path))


# No "both": once the change's own run is refused, dev is never run, so it would be the "change" case again.
@pytest.mark.parametrize("refused", ["change", "base"])
@pytest.mark.parametrize("name", sorted(FAILS))
def test_what_was_proven_alone_still_sends_the_change_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str, name: str
) -> None:
    with_change, on_dev, lint, size, shown = FAILS[name]

    checked = _check(tmp_path, monkeypatch, refused, (with_change, on_dev), lint, size)

    assert checked.state == check.FAILED and checked.failed, name
    assert shown in checked.findings
    assert "could not be started" in checked.findings and NO_PLACE in checked.findings, (
        "the team is told it was partial"
    )
    assert (
        report.HEADINGS["unconfirmed"] not in checked.findings and report.HEADINGS["timed_out"] not in checked.findings
    )


@pytest.mark.parametrize("refused", ["change", "base"])
@pytest.mark.parametrize("name", sorted(HELD))
def test_what_the_incomplete_runs_cannot_settle_only_holds_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str, name: str
) -> None:
    checked = _check(tmp_path, monkeypatch, refused, HELD[name], CLEAN, [])

    assert checked.state == check.UNAVAILABLE and not checked.failed, name
    assert (checked.cause, checked.costly) == ("busy", False) and not checked.findings
    assert NO_PLACE in checked.line


def test_a_run_that_broke_next_to_a_refused_shard_only_holds_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broke = "tests/test_other.py: pytest exited 2: boom; "

    checked = _check(tmp_path, monkeypatch, "change", (PASSED, PASSED), CLEAN, [], run_trouble=broke)

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, "busy", False)
    assert "pytest exited 2" not in checked.line, "the reason is the refusal's"


@pytest.mark.parametrize("refused", ["with the change", "on dev"])
def test_a_re_run_on_its_own_the_pool_gave_no_place_only_holds_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str
) -> None:
    # runner.NO_PLACE is read here, not at collection, so the rest of this file also runs on a dev without it.
    alone = (runner.NO_PLACE, PASSED) if refused == "with the change" else (FAILED, runner.NO_PLACE)

    held = _check(tmp_path, monkeypatch, "", alone, CLEAN, [])

    assert (held.state, held.cause, held.costly) == (check.UNAVAILABLE, "busy", False) and not held.findings
    assert "got no place in the pool" in held.line, "it says why, and it is never a failure nobody could settle"
    assert "not everything could be compared" in held.line and "nothing was compared" not in held.line

    linted = _check(tmp_path, monkeypatch, "", alone, LintResult(True, "", (RUFF,), ()), [])

    assert linted.state == check.FAILED and RUFF in linted.findings and "could not be started" in linted.findings
