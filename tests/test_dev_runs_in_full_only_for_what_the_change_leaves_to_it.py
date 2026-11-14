"""Dev is run in full only for what the change's run leaves to it, and its answer counts only as far as it goes.

Spec 2026-10-12 Part 1 item 3 and Decision 10, guarded where review of Task 19 found nothing pinning them:
- at most 40 failures, some that no re-run on its own could settle and nothing else: dev runs in full, and the check is
  held as dev's (no strike) only when dev's own run fails every one of them;
- a timed-out re-run, a failing test the change adds or a failure past the cap is the change's, whatever dev does;
- a dev run the pool refused proves nothing about dev, and a change whose own run was refused never runs dev in full;
- while the tests are held for dev, ruff and the size rule still send the change back;
- the findings never claim a re-run that did not happen.
Sibling of ``test_the_change_runs_once_and_dev_only_when_needed.py``, whose stand-in proof step it uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_the_change_runs_once_and_dev_only_when_needed import TEST, Copies, _copies, _many
from thomas.server.precard import check, report
from thomas.server.precard.lint import LintResult
from thomas.server.proof import ProofRun, runner

OTHER = "tests/test_x.py::test_other"
REGRESSION = "tests/test_x.py::test_regressed"
NO_PLACE = "the pool's reservation ledger could not be used, so the shard did not start: stayed locked"
RUFF = "pkg/x.py:3:1: F401 `os` imported but unused"
SIZE = "pkg/x.py is 900 lines, over the 800-line limit"
EACH = "Each failure was then re-run on its own"


@pytest.fixture
def copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Copies:
    return _copies(tmp_path, monkeypatch)


def _refused(failed: tuple[str, ...] = ()) -> ProofRun:
    return ProofRun(False, NO_PLACE, failed, 1, 2, not_started=("tests/test_x.py",), not_started_why=NO_PLACE)


# ── at most 40 failures, some no re-run on its own could settle (review I1) ──────────────────────────────


def test_a_failure_no_re_run_settled_that_dev_also_fails_holds_the_check_as_devs(copies: Copies) -> None:
    copies.change_run = copies.dev_run = ProofRun(True, "", (TEST,), 5, 1)  # its re-run with the change: unknown

    checked = copies.check()

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, "dev-side", False)
    assert copies.runs == ["change", "base"]


def test_a_failure_no_re_run_settled_that_dev_passes_goes_back(copies: Copies) -> None:
    copies.change_run = ProofRun(True, "", (TEST,), 5, 1)

    checked = copies.check()

    assert checked.state == check.FAILED and report.HEADINGS["unconfirmed"] in checked.findings
    assert TEST in checked.findings and copies.runs == ["change", "base"]


def test_forty_flaky_failures_and_one_past_the_cap_that_dev_passes_go_back(copies: Copies) -> None:
    late = "tests/test_x.py::test_late"
    copies.change_run = ProofRun(True, "", (*_many(40), late), 41, 1)
    for test in _many(40):
        copies.alone_change[test] = runner.PASSED

    checked = copies.check()

    assert checked.state == check.FAILED and late in checked.findings
    assert report.HEADINGS["unconfirmed"] in checked.findings and copies.runs == ["change", "base"]


@pytest.mark.parametrize(
    "alone, on_dev, heading",
    [(runner.TIMEOUT, runner.UNKNOWN, "timed_out"), (runner.FAILED, runner.MISSING, "added_fail")],
    ids=["a re-run that timed out", "a failing test the change adds"],
)
def test_a_finding_beside_an_unsettled_failure_dev_also_fails_still_goes_back(
    copies: Copies, alone: str, on_dev: str, heading: str
) -> None:
    copies.change_run = ProofRun(True, "", (OTHER, TEST), 5, 1)
    copies.dev_run = ProofRun(True, "", (TEST,), 5, 1)
    copies.alone_change[OTHER], copies.alone_dev[OTHER] = alone, on_dev

    checked = copies.check()

    assert checked.state == check.FAILED and report.HEADINGS[heading] in checked.findings
    assert copies.runs == ["change"], "the change's own finding needs no dev run"


def test_an_unsettled_failure_whose_dev_run_the_pool_refused_only_holds_the_check(copies: Copies) -> None:
    copies.change_run = ProofRun(True, "", (TEST,), 5, 1)
    copies.dev_run = _refused((TEST,))  # dev's started shards failed it too: still not dev's, nothing finished there

    checked = copies.check()

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, "busy", False)
    assert NO_PLACE in checked.line and copies.runs == ["change", "base"]


@pytest.mark.parametrize("change_ran", [True, False], ids=["the change's run finished", "neither finished"])
def test_dev_that_breaks_holds_the_check_in_words_that_are_true(copies: Copies, change_ran: bool) -> None:
    """Review m1: "did not run to the end on dev itself either" was said when the change's own run had finished."""
    copies.change_run = ProofRun(change_ran, "" if change_ran else "pytest exited 3", (TEST,), 5, 1)
    copies.dev_run = ProofRun(False, "pytest exited 3", (), 0, 1)

    checked = copies.check()

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, "dev-side", False)
    where = "on dev itself:" if change_ran else "with this change or on dev itself:"
    assert f"did not run to the end {where}" in checked.line and "either" not in checked.line


@pytest.mark.parametrize("dev", ["finishes", "is refused a place"])
def test_a_change_whose_own_test_process_would_not_start_is_the_checks_strike_and_never_runs_dev(
    copies: Copies, dev: str
) -> None:
    """Whole review I1: it went back FAILED as "broke" when dev's run finished, and busy when dev's was refused."""
    why = "tests/test_x.py: it could not be started: [WinError 5] Access is denied"
    copies.change_run = ProofRun(False, why, (), 0, 1, not_launched=("tests/test_x.py",))
    copies.dev_run = ProofRun(True, "", (), 5, 1) if dev == "finishes" else _refused()

    checked = copies.check()

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, "incomplete", True)
    assert "would not start" in checked.line and copies.runs == ["change"]


# ── the wiring around it (review m4) ───────────────────────────────────────────────────────────────────


def test_a_change_whose_own_run_the_pool_refused_never_runs_dev_in_full(copies: Copies) -> None:
    copies.change_run = _refused((TEST,))  # did not finish, and a failure no re-run settles

    checked = copies.check()

    assert (checked.state, checked.cause) == (check.UNAVAILABLE, "busy") and copies.runs == ["change"]


# ── while the tests are held for dev (review m2) ───────────────────────────────────────────────────────


@pytest.mark.parametrize("many", [True, False], ids=["more than 40 that dev also fails", "one that dev also fails"])
def test_ruff_and_the_size_rule_still_send_a_change_back_while_its_tests_are_held_for_dev(
    copies: Copies, monkeypatch: pytest.MonkeyPatch, many: bool
) -> None:
    monkeypatch.setattr(check.lint, "ruff_findings", lambda *_a, **_k: LintResult(True, "", (RUFF,), ()))
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_a: [SIZE])
    failed = _many(41) if many else (TEST,)
    copies.change_run = copies.dev_run = ProofRun(True, "", failed, 41, 1)

    checked = copies.check()

    assert checked.state == check.FAILED and RUFF in checked.findings and SIZE in checked.findings
    assert "were not counted against it" in checked.findings, "the team is told why its tests are not listed"
    assert report.HEADINGS["unconfirmed"] not in checked.findings
    assert (EACH not in checked.findings) if many else (EACH in checked.findings), "no re-run is claimed falsely"


# ── the findings head on the refusal path (review m5) ──────────────────────────────────────────────────


def test_on_the_refusal_path_the_findings_never_claim_a_re_run_that_got_no_place(copies: Copies) -> None:
    copies.change_run = ProofRun(True, "", (REGRESSION, TEST), 5, 1)
    copies.alone_change[REGRESSION], copies.alone_dev[REGRESSION] = runner.FAILED, runner.PASSED
    copies.alone_change[TEST] = runner.NO_PLACE

    checked = copies.check()

    assert checked.state == check.FAILED and REGRESSION in checked.findings and EACH not in checked.findings
    assert "1 of its 2 failures were then each re-run on its own" in checked.findings
    assert "1 given no place in the pool of test processes" in checked.findings


def test_on_the_refusal_path_the_findings_never_claim_a_re_run_past_the_cap(copies: Copies) -> None:
    copies.change_run = _refused((REGRESSION, *_many(44)))
    copies.alone_change[REGRESSION], copies.alone_dev[REGRESSION] = runner.FAILED, runner.PASSED

    checked = copies.check()

    assert checked.state == check.FAILED and REGRESSION in checked.findings and EACH not in checked.findings
    assert "The first 40 of its 45 failures were then each re-run on its own" in checked.findings
