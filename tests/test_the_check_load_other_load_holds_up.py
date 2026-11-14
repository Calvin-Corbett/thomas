"""A load run's record of other load holds up at its edges: a slow walk, a failed reading, a window with no reading,
a machine that cannot be read, a --wait-quiet that could never succeed, and the job every process ends with.

Found in review of the first version (2026-10-13). The record decides whether a run's times are trusted or thrown out,
so an edge that reads as other load, or as quiet, when it is neither, would undo what it is for.
"""

from __future__ import annotations

import ctypes
import itertools
import logging
import os
import threading
import time
from collections import namedtuple
from types import SimpleNamespace

import pytest
from scripts.praxis import check_load, check_load_job, check_load_machine, check_load_record
from scripts.praxis.check_load_machine import Reading

from tests.test_the_check_load_run_records_other_load import _entry, _result
from thomas.server.precard import check

_Own = namedtuple("_Own", "user system")  # a process's cpu_times()
_Machine = namedtuple("_Machine", "user system idle")  # the machine's cpu_times()


class _Root:
    pid = 1

    def __init__(self, ps: _Busy) -> None:
        self.ps = ps

    def children(self, recursive: bool = False) -> list[_Root]:
        self.ps.now += next(self.ps.steps)  # the walk takes a while, and the run's own work goes on meanwhile
        return []

    def cpu_times(self) -> _Own:
        return _Own(12 * self.ps.now, 0.0)

    def is_running(self) -> bool:
        return True


class _Busy:
    """psutil on a machine whose only work is this run's, on 12 of its 16 threads; each walk takes 0.5 s, then 1.5 s."""

    Error, AccessDenied = OSError, PermissionError

    def __init__(self) -> None:
        self.now, self.steps, self.root = 0.0, itertools.cycle((0.5, 1.5)), _Root(self)

    def Process(self, pid: int) -> _Root:  # noqa: N802 - psutil's own name
        return self.root

    def cpu_times(self) -> _Machine:
        return _Machine(12 * self.now, 0.0, 4 * self.now)

    def process_iter(self, attrs: list[str]) -> list[_Root]:
        return []


@pytest.mark.parametrize("job", [True, False], ids=["own CPU from the job", "own CPU from the walk"])
def test_how_long_the_walk_takes_never_reads_as_other_load(job: bool) -> None:
    ps = _Busy()
    job_cpu = (lambda: 12 * ps.now) if job else (lambda: None)
    sampler = check_load_machine.Sampler(psutil_mod=ps, root_pid=1, clock=lambda: ps.now, job_cpu=job_cpu)

    assert [sampler.read().other_pct for _ in range(6)] == [None, 0.0, 0.0, 0.0, 0.0, 0.0]


@pytest.mark.skipif(os.name != "nt", reason="a Windows job")
def test_the_job_ends_every_process_with_the_run_and_lets_one_that_asks_leave_it() -> None:
    kernel = check_load_job._kernel()
    handle = check_load_job._new_job(kernel)  # made, read back and closed; no process is ever put in it
    limits = check_load_job._Limits()
    read = handle and kernel.QueryInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None)
    if handle:
        kernel.CloseHandle(handle)

    assert read, "Windows refused the job's limits, so the run would count its own CPU by the walk alone"
    assert limits.LimitFlags == 0x2800, "kill on close and breakaway allowed, and nothing else"


def test_a_check_whose_window_had_no_reading_is_listed_apart_as_not_measured() -> None:
    unseen = {"execution_id": "load-e-3", "state": "passed", "cause": "", "seconds": 9.0, "ran_from": 50.0}
    unseen["ran_to"] = 60.0
    check_load_record.load_window(unseen, [])

    lines = check_load_record.load_lines(_result([_entry("load-e-1", 3.0, 0), _entry("load-e-2", 70.0, 2), unseen]))

    assert lines[0].startswith("NOT QUIET") and "1 of 3 checks" in lines[0] and "load-e-2" in lines[1]
    assert lines[2].startswith("OTHER LOAD NOT MEASURED") and "load-e-3" in lines[2]
    assert "load-e-3" not in "\n".join(lines[:2]), "a check nothing was read for is not said to have overlapped"


def _window(execution_id: str, readings: list[Reading]) -> dict:
    entry = {"execution_id": execution_id, "state": "passed", "cause": "", "seconds": 300.0, "ran_from": 0.0}
    entry["ran_to"] = 300.0
    check_load_record.load_window(entry, readings)
    return entry


def test_a_check_read_for_only_part_of_its_window_is_not_measured_and_never_quiet() -> None:
    few = _window("load-g-1", [Reading(10.0 + s, 1.0, 3.0, 0) for s in range(3)])  # a few good readings in 300 s
    died = _window("load-g-2", [Reading(1.0 + s, 1.0, 3.0, 0) for s in range(100)])  # the reader stopped at 100 s
    enough = _window("load-g-3", [Reading(1.0 + s, 1.0, 3.0, 0) for s in range(240)])  # 80% read is enough

    assert few["quiet"] is False and died["quiet"] is False, "what was read was quiet, but too little was read"
    assert (few["other_load_measured_s"], died["other_load_measured_s"], few["other_load_window_s"]) == (3, 100, 300)
    assert [entry["other_load_measured"] for entry in (few, died, enough)] == [False, False, True]
    assert enough["quiet"] is True
    lines = check_load_record.load_lines(_result([few, died, enough]))
    assert lines == ["OTHER LOAD NOT MEASURED while load-g-1 (3 of 300 s read), load-g-2 (100 of 300 s read) ran:"
                     " nothing shows whether other work slowed them"]  # fmt: skip


@pytest.mark.parametrize("fault", [KeyError, SystemError], ids=["a lookup", "psutil's compiled part"])
def test_a_reading_that_raises_is_kept_as_not_measured_and_the_readings_go_on(
    fault: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[int] = []

    def read() -> Reading:
        calls.append(1)
        if len(calls) == 1:
            raise fault("a reading the sampler did not expect")
        return Reading(time.time(), 0.01, 3.0, 0)

    done, readings = threading.Event(), []
    with caplog.at_level(logging.WARNING):
        thread = check_load_machine.watch(SimpleNamespace(read=read), 0.01, done, readings)
        end = time.monotonic() + 5
        while len(readings) < 3 and time.monotonic() < end:
            time.sleep(0.01)
        done.set()
        thread.join(5)

    assert len(readings) >= 3 and (readings[0].other_pct, readings[0].browsers) == (None, None)
    assert readings[2].other_pct == 3.0, "the thread went on reading"
    assert fault.__name__ in caplog.text, "and said what went wrong"


def test_without_psutil_the_run_says_it_did_not_wait_not_that_it_never_got_quiet() -> None:
    said: list[str] = []
    waited = check_load_machine.wait_quiet(SimpleNamespace(available=False), 600, say=said.append)
    entry = {"execution_id": "load-f-1", "state": "passed", "cause": "", "seconds": 9.0, "ran_from": 0.0, "ran_to": 9}
    check_load_record.load_window(entry, [])
    result = {"checks": [entry], **check_load_record.load_summary([entry], [], waited, None)}

    lines = check_load_record.load_lines(result)

    assert (waited["got_quiet"], waited["measured"], waited["waited_s"]) == (False, False, 0.0)
    assert lines[0].startswith("DID NOT WAIT") and lines[1].startswith("OTHER LOAD NOT MEASURED")
    assert "NEVER GOT QUIET" not in "\n".join(lines) and "cannot be measured" in said[0]


@pytest.mark.parametrize("seconds", ["30", "59.9", "nan", "inf", "-1"])
def test_wait_quiet_refuses_a_value_that_could_never_get_quiet(
    seconds: str, tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(check.CHECK_ENV, raising=False)
    monkeypatch.setattr(check_load, "pick_modules", lambda blue, **kwargs: [("thomas/a.py", 25)] * 2)
    monkeypatch.setattr(check_load, "run_load", lambda *args, **kwargs: pytest.fail("the run started"))
    argv = ["--count", "2", "--blue", str(tmp_path), "--out-dir", str(tmp_path / "out"), "--wait-quiet", seconds]

    with pytest.raises(SystemExit):
        check_load.main(argv)
    assert "--wait-quiet" in capsys.readouterr().err


def test_the_wait_line_shows_a_dash_for_what_was_not_read() -> None:
    blind, said = SimpleNamespace(available=True, now=0.0), []
    blind.read = lambda: Reading(blind.now, 1.0, None, None)

    def sleep(seconds: float) -> None:
        blind.now += seconds

    check_load_machine.wait_quiet(blind, 61, clock=lambda: blind.now, sleep=sleep, say=said.append)

    assert len(said) == 1 and "None" not in said[0] and "- headless browser processes" in said[0]
