"""A test process that died without a report is run once more before the check gives up.

On 2026-11-10 a finished change's check ran 59 minutes with ten Builds filling the PC. Every shard of the change's
side finished. On dev's side one shard's pytest was ended by the 300-second test timeout, which kills the process and
leaves no report: "shard 1 of 18: its report has no test case for ... (no report; pytest said: ... Timeout". That one
dead process made the whole check "unavailable", to be tried again two hours later from the start: about twelve hours
of processor time for no answer.

Now the shard whose process ended with no report at all is run again, once, while the deadline allows. A second death
is reported as before. A shard the pool refused, or one that ran out of its own time, is not run again here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.test_a_shard_that_did_not_finish_proves_and_measures_nothing import CASE, NO_PLACE, _files
from tests.test_checks_share_one_machine_wide_pool import _report
from thomas.server.proof import runner
from thomas.server.proof.deadline import Deadline
from thomas.server.proof.environment import REFUSED, TIMED_OUT

DIED = "+++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++++++"


def _run_tests(tmp_path: Path, files: list[str], run, **more):
    return runner.run_tests(
        tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", shard_files=1, run=run, **more
    )


@pytest.mark.parametrize("workers", [1, 2])
def test_a_shard_that_died_once_is_run_again_and_its_tests_count(tmp_path: Path, workers: int) -> None:
    files = _files(tmp_path, ("a", "b"))
    calls: list[str] = []

    def run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        report = _report(command)
        calls.append(report.name)
        if report.name == "shard-1.xml" and calls.count("shard-1.xml") == 1:
            return 1, DIED  # the test timeout ended the process: no report was written
        report.write_text(CASE.format(n="a" if report.name == "shard-1.xml" else "b"), encoding="utf-8")
        return 0, ""

    result = _run_tests(tmp_path, files, run, shard_workers=workers)

    assert result.ran and result.seen == 2 and result.unrun == ()
    assert calls.count("shard-1.xml") == 2 and calls.count("shard-2.xml") == 1


def test_a_shard_that_dies_twice_is_reported_and_not_run_a_third_time(tmp_path: Path) -> None:
    files = _files(tmp_path, ("a",))
    calls: list[str] = []

    def run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        calls.append(_report(command).name)
        return 1, DIED

    result = _run_tests(tmp_path, files, run)

    assert not result.ran and "its report has no test case for tests/test_a.py" in result.why
    assert len(calls) == 2


@pytest.mark.parametrize(("code", "said"), [(REFUSED, NO_PLACE), (TIMED_OUT, "it did not finish within 1800s")])
def test_a_refused_or_timed_out_shard_is_not_run_again(tmp_path: Path, code: int, said: str) -> None:
    files = _files(tmp_path, ("a",))
    calls: list[str] = []

    def run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        calls.append(_report(command).name)
        return code, said

    assert not _run_tests(tmp_path, files, run).ran
    assert len(calls) == 1


def test_the_record_keeps_why_each_side_did_not_finish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev runs in full only when the change's own run did not finish, and the check's sentence names dev's trouble."""
    from tests.test_checks_share_one_machine_wide_pool import GIB, _quiet_steps, _steps_args
    from thomas.server.precard import check, clocks
    from thomas.server.proof import ProofRun

    _quiet_steps(monkeypatch)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * GIB, 20 * GIB))
    whys = iter(["shard 3 of 20: the change's process died", "shard 1 of 18: dev's process died"])
    monkeypatch.setattr(check.proofs, "run_tests", lambda *_a, **_k: ProofRun(False, next(whys), (), 0, 1))

    with clocks.recording(tmp_path, "fc_example") as record:
        checked = check._steps(*_steps_args(tmp_path))

    assert checked.state == check.UNAVAILABLE and checked.cause == "dev-side"
    assert record["change_run_why"] == "shard 3 of 20: the change's process died"
    assert record["dev_run_why"] == "shard 1 of 18: dev's process died"


def test_a_dead_shard_is_not_run_again_once_the_deadline_has_passed(tmp_path: Path) -> None:
    files = _files(tmp_path, ("a",))
    deadline = Deadline(60.0)
    calls: list[str] = []

    def run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        calls.append(_report(command).name)
        deadline.seconds = 0.0  # the check's time ran out while this shard was running
        return 1, DIED

    assert not _run_tests(tmp_path, files, run, deadline=deadline).ran
    assert len(calls) == 1
