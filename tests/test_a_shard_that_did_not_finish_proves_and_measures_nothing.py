"""A shard the pool refused is neither a failure nor a pass; a shard that did not finish leaves no memory peak.

A shard the pool refuses a place (its ledger cannot be used, or it refused one before the deadline) answers
``REFUSED``. Read as the change's side of a check, that failed a change on a machine that was merely unable to start
the tests; read as dev's side, it was a strike against the change. Now ``ProofRun.not_started`` carries it out of
``run_tests`` and the check is held for another try (``UNAVAILABLE``, cause ``busy``, no strike), whichever side was
refused (dev is run in full only when the change's run did not finish), unless something proven alone fails it (the
sibling about a refused shard that still reports what it proved alone). Only a refusal that comes with the deadline
spent is out of time. A command that would not launch (``NOT_STARTED``) is not the pool's refusal and keeps the earlier
reading, so with ``THOMAS_PRECARD_PARALLEL=off`` nothing reads as busy. A shard that crashed before its first real
sample must not pull the p90 of measured shard memory the wrong way either, so only a shard that finished is recorded.
Sibling of ``test_checks_share_one_machine_wide_pool.py``, which stays under the 300-line cap.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_checks_share_one_machine_wide_pool import GIB, _quiet_steps, _report, _steps_args
from thomas.server import capacity_ledger, capacity_ledger_locks, precard
from thomas.server.precard import check, pool
from thomas.server.proof import ProofRun, runner
from thomas.server.proof.deadline import Deadline
from thomas.server.proof.environment import NOT_STARTED, REFUSED, TIMED_OUT

NO_PLACE = "the pool's reservation ledger could not be used, so the shard did not start: stayed locked"
BOOM = "it could not be started: [WinError 5] Access is denied"
CASE = '<testsuite><testcase classname="tests.test_{n}" file="tests/test_{n}.py" name="test_ok"/></testsuite>'


def _files(work: Path, names: tuple[str, ...]) -> list[str]:
    for name in names:
        (work / "tests").mkdir(parents=True, exist_ok=True)
        (work / "tests" / f"test_{name}.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    return [f"tests/test_{name}.py" for name in names]


@pytest.mark.parametrize("folder", [False, True])
def test_run_tests_names_the_files_of_a_shard_the_pool_refused(tmp_path: Path, folder: bool) -> None:
    files = _files(tmp_path, ("a", "b"))

    def run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        report = _report(command)
        if report.name == "shard-1.xml":
            return REFUSED, NO_PLACE
        report.write_text(CASE.format(n="b"), encoding="utf-8")
        return 0, ""

    result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", shard_files=1,
                              shard_workers=2, folder=folder, run=run)  # fmt: skip

    assert not result.ran and not result.out_of_time and result.failed == () and result.seen == 1
    assert result.not_started == ("tests/test_a.py",) and result.not_started_why == NO_PLACE


def test_the_refusal_is_named_apart_from_the_trouble_of_other_shards(tmp_path: Path) -> None:
    files = _files(tmp_path, ("a", "b"))

    def run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        return (2, "internal error") if _report(command).name == "shard-1.xml" else (REFUSED, NO_PLACE)

    result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", shard_files=1, run=run)

    assert result.not_started == ("tests/test_b.py",) and result.not_started_why == NO_PLACE
    assert "pytest exited 2" in result.why and "internal error" not in result.not_started_why


@pytest.mark.parametrize(
    "answer", [(2, "internal error"), (NOT_STARTED, BOOM)], ids=["a crash", "a command that would not launch"]
)
def test_a_shard_that_started_and_broke_or_would_not_launch_is_not_one_the_pool_refused(
    tmp_path: Path, answer: tuple[int, str]
) -> None:
    files = _files(tmp_path, ("a",))

    result = runner.run_tests(
        tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", run=lambda *_a, **_k: answer
    )

    assert not result.ran and result.not_started == () and result.not_started_why == "" and result.why


@pytest.mark.parametrize("refused", ["change", "base"])
def test_a_refusal_in_one_sides_run_holds_the_check_and_is_not_a_strike(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str
) -> None:
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    _quiet_steps(monkeypatch)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * GIB, 20 * GIB))
    others = "tests/test_ok.py: pytest exited 2: boom; "

    def fake_tests(work: Path, files: tuple, **_kwargs: object) -> ProofRun:
        if work.name == refused:
            return ProofRun(False, others + NO_PLACE, (), 0, 1, not_started=tuple(files), not_started_why=NO_PLACE)
        if refused == "base":  # dev runs in full only when the change's run did not finish
            return ProofRun(False, others, (), 0, 1)
        return ProofRun(True, "", (), 1, 1)

    monkeypatch.setattr(check.proofs, "run_tests", fake_tests)

    checked = check._steps(*_steps_args(tmp_path))

    assert checked.state == precard.UNAVAILABLE and not checked.failed
    assert (checked.cause, checked.costly) == ("busy", False)
    assert "Not checked before this card" in checked.line and NO_PLACE in checked.line
    assert "pytest exited 2" not in checked.line, "the reason is the refusal's, not another shard's trouble"


@pytest.mark.parametrize("refused, broke", [("change", False), ("base", True), (None, False), (None, True)])
def test_a_check_whose_pool_refuses_one_side_is_unavailable_never_failed_or_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str | None, broke: bool
) -> None:
    """*broke*: the change's run did not finish, so dev is run in full, which is when dev's place can be refused."""
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    _quiet_steps(monkeypatch)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * GIB, 20 * GIB))
    for side in ("base", "change"):
        _files(tmp_path / side, ("ok",))

    def pool_runner(_deadline: object, *, files: int, record_peaks: bool = True, waits: object = None) -> object:
        def run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
            if cwd.name == refused:
                return REFUSED, NO_PLACE
            if broke and cwd.name == "change":
                return 2, "internal error"
            _report(command).write_text(CASE.format(n="ok"), encoding="utf-8")
            return 0, ""

        return run

    monkeypatch.setattr(check.pool, "runner", pool_runner)

    checked = check._steps(*_steps_args(tmp_path))

    if refused is None:
        answer = precard.FAILED if broke else precard.PASSED
        assert checked.state == answer, "the same runs with no refusal get an answer, so the refusal is what held it"
    else:
        assert checked.state == precard.UNAVAILABLE and (checked.cause, checked.costly) == ("busy", False)
        assert NO_PLACE in checked.line and not checked.findings


@pytest.mark.parametrize("launch_fails", ["change", "base", "both"])
def test_with_the_pool_off_a_pytest_that_would_not_launch_is_never_busy_and_never_devs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launch_fails: str
) -> None:
    monkeypatch.setenv(pool.PARALLEL_ENV, "off")
    _quiet_steps(monkeypatch)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * GIB, 20 * GIB))
    for side in ("base", "change"):
        _files(tmp_path / side, ("ok",))
    launched: list[str] = []

    def fake_run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        launched.append(cwd.name)
        if launch_fails in (cwd.name, "both"):
            return NOT_STARTED, BOOM
        _report(command).write_text(CASE.format(n="ok"), encoding="utf-8")
        return 0, ""

    original = check.proofs.run_tests
    monkeypatch.setattr(
        check.proofs, "run_tests", lambda work, files, **kw: original(work, files, **{**kw, "run": fake_run})
    )

    checked = check._steps(*_steps_args(tmp_path))

    if launch_fails == "base":  # the change's run finished clean, so dev is never run in full
        assert checked.state == precard.PASSED and "base" not in launched
    else:  # the change's own pytest would not launch: the check's machinery, a strike whatever dev does
        assert (checked.state, checked.cause, checked.costly) == (precard.UNAVAILABLE, "incomplete", True)
        assert "base" not in launched and BOOM in checked.line, "dev is not run for the check's own trouble"


@pytest.fixture
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(capacity_ledger, "measure", lambda _where: capacity_ledger.Room(100 * GIB, 64 * GIB, 64 * GIB))
    monkeypatch.setattr(pool.machine_capacity, "check_shard_mb", lambda *_a: 100)
    monkeypatch.setattr(pool.green_checkout, "green_root", lambda: tmp_path)


@pytest.mark.parametrize(
    "code, kept",
    [(0, True), (1, True), (5, True), (2, False), (3, False), (4, False), (-1073741819, False)]
    + [(TIMED_OUT, False), (NOT_STARTED, False), (REFUSED, False)],
)
def test_only_a_shard_that_finished_leaves_its_memory_peak(
    tmp_path: Path, ledger: None, monkeypatch: pytest.MonkeyPatch, code: int, kept: bool
) -> None:
    recorded: list[tuple[float, float]] = []
    monkeypatch.setattr(pool.machine_capacity, "record_check_shard_peak", lambda c, w: recorded.append((c, w)))
    monkeypatch.setattr(pool, "run_measured", lambda *_a, **_k: (code, "output", 321.0, 45.0))

    assert pool.runner(None, files=1)(["x"], cwd=tmp_path, env={}, timeout_s=10) == (code, "output")

    assert recorded == ([(321.0, 45.0)] if kept else []), f"a shard that exited {code}"


@pytest.mark.parametrize("waited", [False, True], ids=["nothing could give room back", "it waited as long as it may"])
def test_a_place_the_ledger_refuses_before_the_deadline_is_a_refusal_never_a_timeout(
    tmp_path: Path, ledger: None, monkeypatch: pytest.MonkeyPatch, waited: bool
) -> None:
    """Review of the whole change, finding I2: every NotAdmitted read as TIMED_OUT, the change breaking the run."""

    def full(*_a: object, **_k: object) -> None:
        raise capacity_ledger.NotAdmitted("all 3 places are in use", waited=waited)

    monkeypatch.setattr(pool.capacity_ledger, "admitted", full)
    monkeypatch.setattr(pool, "run_measured", lambda *_a, **_k: pytest.fail("a shard ran without its place"))

    for deadline in (None, Deadline(600)):
        code, output = pool.runner(deadline, files=1)(["x"], cwd=tmp_path, env={}, timeout_s=10)
        assert code == REFUSED and "all 3 places are in use" in output, f"deadline {deadline}"

    spent = pool.runner(Deadline(0.0), files=1)(["x"], cwd=tmp_path, env={}, timeout_s=10)
    assert spent[0] == TIMED_OUT, "a refusal that comes with the deadline spent is out of time, whatever refused it"


@pytest.mark.parametrize("waited", [False, True])
def test_a_check_whose_places_were_refused_before_its_deadline_is_unavailable_never_failed(
    tmp_path: Path, ledger: None, monkeypatch: pytest.MonkeyPatch, waited: bool
) -> None:
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    _quiet_steps(monkeypatch)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * GIB, 20 * GIB))
    for side in ("base", "change"):
        _files(tmp_path / side, ("ok",))

    def full(*_a: object, **_k: object) -> None:
        raise capacity_ledger.NotAdmitted("all 1 places are in use", waited=waited)

    monkeypatch.setattr(pool.capacity_ledger, "admitted", full)

    checked = check._steps(*_steps_args(tmp_path))

    assert checked.state == precard.UNAVAILABLE and (checked.cause, checked.costly) == ("busy", False)
    assert "all 1 places are in use" in checked.line and not checked.findings


def test_a_wall_clock_that_steps_forward_while_a_shard_waits_does_not_end_its_wait(
    tmp_path: Path, ledger: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wait is timed on the monotonic clock: an NTP step of two hours made every waiting shard give up at once."""
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    _quiet_steps(monkeypatch)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * GIB, 20 * GIB))
    monkeypatch.setattr(pool, "size", lambda **_k: 1)
    monkeypatch.setattr(capacity_ledger, "POLL_S", 0.02)
    step = [0.0]
    stepped = SimpleNamespace(time=lambda: time.time() + step[0], monotonic=time.monotonic, sleep=time.sleep)
    monkeypatch.setattr(capacity_ledger, "time", stepped)
    for side in ("base", "change"):
        _files(tmp_path / side, ("ok",))

    def measured(command: list[str], *, cwd: Path, env: dict, timeout_s: float, sample_s: float = 0.5) -> tuple:
        _report(command).write_text(CASE.format(n="ok"), encoding="utf-8")
        return 0, "", 0.0, 0.0

    monkeypatch.setattr(pool, "run_measured", measured)
    held, release = threading.Event(), threading.Event()

    def other_check() -> None:  # the other server's shard holds the only place for a moment
        with capacity_ledger.admitted("shard:other", kind=pool.SHARD_KIND, where=tmp_path, limit=1):
            held.set()
            release.wait(20)

    threading.Thread(target=other_check, daemon=True).start()
    assert held.wait(10)
    threading.Timer(0.3, lambda: step.__setitem__(0, 7200.0)).start()  # the wall clock steps two hours forward
    threading.Timer(1.0, release.set).start()

    checked = check._steps(*_steps_args(tmp_path))

    assert step[0] == 7200.0 and checked.state == precard.PASSED, checked.line


def test_a_row_a_live_server_wrote_wrongly_holds_a_check_and_is_never_a_strike(
    tmp_path: Path, ledger: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    _quiet_steps(monkeypatch)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * GIB, 20 * GIB))
    for side in ("base", "change"):
        _files(tmp_path / side, ("ok",))
    place = capacity_ledger.folder()
    mine = capacity_ledger_locks.owner(place)
    row = {"key": "p", "owner": mine, "kind": "pool_size", "pool_size": 12}  # it has no id and no state
    (place / capacity_ledger.NAME).write_text(json.dumps([row]), encoding="utf-8")
    capacity_ledger_locks.hold("a-running-job")  # a running job may have rows in the file: it is not moved aside
    try:
        checked = check._steps(*_steps_args(tmp_path))
    finally:
        capacity_ledger_locks.let_go("a-running-job")

    assert checked.state == precard.UNAVAILABLE and (checked.cause, checked.costly) == ("busy", False)
    assert "cannot be read" in checked.line and not checked.findings
