"""A load run records how busy the machine was with other work while each check ran, and can wait for a quiet one.

On 2026-10-13 a load run's two slowest checks overlapped a Build team's playtests (headless Chromium on 11 to 14 of
the machine's 16 threads, as thomas-agent), and nothing in the record showed it, so the slowdown was first blamed on
the code under test. Other load is the machine's busy CPU minus the run's own process tree, floored at 0.
"""

from __future__ import annotations

import os
import time
from collections import namedtuple
from types import SimpleNamespace
from typing import Any

import pytest
from scripts.praxis import check_load, check_load_machine, check_load_record
from scripts.praxis.check_load_machine import Reading

from tests.test_the_check_load_run_starts_checks_together import _fake_result, _install
from thomas.server.precard import check

_Times = namedtuple("_Times", "user system idle interrupt dpc")  # psutil.cpu_times() on Windows; dpc is in system
_Error = type("_Error", (Exception,), {})  # psutil.Error
_Denied = type("_Denied", (_Error,), {})  # psutil.AccessDenied


class _Proc:
    def __init__(self, ps: _Psutil, pid: int, ppid: int, cpu: float, name: str, cmd: tuple[str, ...] | None) -> None:
        self.ps, self.pid, self.ppid, self.cpu, self.name, self.cmd, self.alive = ps, pid, ppid, cpu, name, cmd, True
        self.info: dict[str, Any] = {}

    def children(self, recursive: bool = False) -> list[_Proc]:
        found, frontier = [], {self.pid}
        while frontier:  # a child whose parent ended is no longer anyone's child, as on Windows
            kids = [p for p in self.ps.live() if p.ppid in frontier and p not in found]
            found += kids
            frontier = {p.pid for p in kids}
        return found

    def cpu_times(self) -> _Times:
        if not self.alive:
            raise _Error("gone")
        return _Times(self.cpu, 0.0, 0.0, 0.0, 0.0)

    def is_running(self) -> bool:
        return self.alive

    def cmdline(self) -> list[str]:
        if self.cmd is None:
            raise _Denied("another account's process")  # what an ordinary account gets for thomas-agent's
        return list(self.cmd)


class _Psutil:
    Error, AccessDenied = _Error, _Denied

    def __init__(self, times: list[_Times]) -> None:
        self.times, self.procs = times, {}

    def add(self, pid: int, ppid: int = 0, cpu: float = 1.0, name: str = "python.exe", cmd: tuple = ("x",)) -> _Proc:
        self.procs[pid] = _Proc(self, pid, ppid, cpu, name, cmd)
        return self.procs[pid]

    def live(self) -> list[_Proc]:
        return [p for p in self.procs.values() if p.alive]

    def cpu_times(self) -> _Times:
        return self.times.pop(0)

    def Process(self, pid: int) -> _Proc:  # noqa: N802 - psutil's own name
        return self.procs[pid]

    def process_iter(self, attrs: list[str]) -> list[_Proc]:
        for proc in self.live():
            proc.info = {"name": proc.name}
        return self.live()


def _sampler(ps: _Psutil, job: list[float] | None = None) -> check_load_machine.Sampler:
    ticks = iter(range(100))
    job_cpu = (lambda: job.pop(0)) if job else (lambda: None)
    return check_load_machine.Sampler(psutil_mod=ps, root_pid=1, clock=lambda: float(next(ticks)), job_cpu=job_cpu)


def test_other_load_is_the_busy_cpu_minus_this_runs_own_tree_floored_at_zero() -> None:
    ps = _Psutil([_Times(100, 50, 850, 5, 5), _Times(106, 52, 858, 6, 6), _Times(107, 52, 873, 6, 6)])
    root, child = ps.add(1, cpu=1.0), ps.add(2, ppid=1, cpu=0.5)
    sampler = _sampler(ps)

    first = sampler.read()
    root.cpu, child.cpu = 1.5, 2.0  # 2 CPU seconds of the 8 the machine was busy are this run's own
    second = sampler.read()
    child.cpu = 5.0  # the run used more than the machine says was busy: other load is 0, never below
    third = sampler.read()

    assert first.other_pct is None and first.span_s == 0.0, "the first reading is only where the next one starts"
    assert second.other_pct == 37.5, "6 of 16 CPU seconds; interrupt and dpc are inside system, not counted twice"
    assert (second.span_s, third.other_pct, sampler.own_from) == (1.0, 0.0, "process walk")


def test_a_child_that_ended_keeps_its_cpu_and_an_orphaned_one_is_still_this_runs() -> None:
    ps = _Psutil([_Times(0, 0, 0, 0, 0), _Times(3, 1, 12, 0, 0)])
    ps.add(1, cpu=1.0)
    child, grandchild = ps.add(2, ppid=1, cpu=1.0), ps.add(3, ppid=2, cpu=1.0)
    sampler = _sampler(ps)
    sampler.read()

    child.alive = False  # it ended; the CPU it used since the last reading is lost to the walk
    grandchild.cpu = 2.0  # its parent ended, so it is nobody's child, but it is still this run's
    reading = sampler.read()

    assert reading.other_pct == 18.75, "own is 1 s (the orphan); the ended child's earlier CPU is not taken back"
    assert sampler.own()[0] == {1, 3}


def test_the_jobs_cpu_counts_children_that_ended_between_two_readings() -> None:
    ps = _Psutil([_Times(0, 0, 0, 0, 0), _Times(6, 2, 8, 0, 0)])
    ps.add(1, cpu=1.0)
    sampler = _sampler(ps, job=[10.0, 14.0])  # the job holds 4 CPU seconds; the walk saw none of them
    sampler.read()

    assert sampler.read().other_pct == 25.0 and sampler.own_from == "job"


def test_headless_browsers_are_counted_by_name_or_by_a_readable_command_line() -> None:
    ps = _Psutil([_Times(0, 0, 0, 0, 0)])
    ps.add(1, cpu=1.0)
    ps.add(2, ppid=1, name="chrome-headless-shell.exe")  # this run's own: not other load
    ps.add(3, name="chrome-headless-shell.exe")
    ps.add(4, name="chrome.exe", cmd=("chrome.exe", "--type=renderer"))  # your own browser window
    ps.add(5, name="msedge.exe", cmd=("msedge.exe", "--headless=new"))
    ps.add(6, name="chrome.exe", cmd=None)  # another account's: its command line cannot be read
    ps.add(7, name="chrome.exe", cmd=("chrome.exe", "--use-angle=swiftshader-webgl"))
    ps.add(8, name="headless_shell", cmd=("headless_shell",))
    ps.add(9, name="notepad.exe", cmd=None)

    assert _sampler(ps).read().browsers == 5


def test_each_checks_entry_holds_the_other_load_inside_its_own_window() -> None:
    readings = [Reading(5.0, 1.0, 90.0, 9), Reading(11.0, 1.0, 10.0, 0), Reading(12.0, 1.0, 40.0, 0)]
    readings += [Reading(13.0, 1.0, 30.0, 2), *(Reading(14.0 + s, 1.0, 5.0, 0) for s in range(7))]
    readings += [Reading(21.0, 1.0, 95.0, 5), *(Reading(31.0 + s, 1.0, 5.0 + 20 * (s % 2), 0) for s in range(10))]
    loaded, calm, unseen = ({"ran_from": a, "ran_to": b} for a, b in ((10.0, 20.0), (30.0, 40.0), (50.0, 60.0)))

    for entry in (loaded, calm, unseen):
        check_load_record.load_window(entry, readings)

    assert loaded == {"ran_from": 10.0, "ran_to": 20.0, "other_cpu_mean_pct": 11.5, "other_cpu_peak_pct": 40.0,
                      "other_cpu_over_s": 2.0, "headless_browser_processes_max": 2, "other_load_measured_s": 10.0,
                      "other_load_window_s": 10.0, "other_load_measured": True, "quiet": False}  # fmt: skip
    assert calm["quiet"] is True and calm["other_cpu_over_s"] == 0.0, "25% is the limit, not over it"
    assert unseen["quiet"] is False and unseen["other_cpu_peak_pct"] is None, "nothing read is never called quiet"


def _entry(execution_id: str, peak: float, browsers: int) -> dict[str, Any]:
    entry = {"execution_id": execution_id, "state": "passed", "cause": "", "seconds": 300.0, "ran_from": 4.0}
    entry["ran_to"] = 5.0  # the one reading below covers all of it
    check_load_record.load_window(entry, [Reading(5.0, 1.0, peak, browsers)])
    return entry


def _result(checks: list[dict[str, Any]], waited: dict[str, Any] | None = None) -> dict[str, Any]:
    readings = [Reading(5.0, 1.0, max(e["other_cpu_peak_pct"] or 0 for e in checks), 0)] if checks else []
    result = {"checks": checks, "free_disk_min_bytes": 1, "check_disk_peak_bytes": 1}
    return {**result, **check_load_record.load_summary(checks, readings, waited, "job")}


def test_the_summary_says_plainly_when_a_run_was_not_quiet_and_which_checks_overlapped() -> None:
    loaded = _result([_entry("load-a-1", 3.0, 0), _entry("load-a-2", 88.0, 9), _entry("load-a-3", 4.0, 1)])
    calm = _result([_entry("load-b-1", 3.0, 0), _entry("load-b-2", 25.0, 0)])

    lines = check_load_record.summary_lines(loaded)

    assert loaded["quiet"] is False and calm["quiet"] is True
    assert lines[0].startswith("NOT QUIET") and "2 of 3 checks" in lines[0], "said first, before any time"
    named = "\n".join(lines[1:3])
    assert "load-a-2" in named and "88.0%" in named and "9 headless" in named and "load-a-3" in named
    assert "load-a-1" not in "\n".join(lines), "a quiet check is not listed as overlapping"
    assert check_load_record.summary_lines(calm)[0].startswith("quiet:")
    assert loaded["other_load"] == {"limit_pct": 25.0, "own_cpu_from": "job", "readings": 1, "other_cpu_mean_pct": 88.0,
                                    "other_cpu_peak_pct": 88.0, "other_cpu_over_s": 1.0,
                                    "headless_browser_processes_max": 0}  # fmt: skip


def test_a_run_whose_load_was_not_read_says_so_and_an_older_summary_still_prints() -> None:
    blind = _result([{**_entry("load-c-1", 1.0, 0), "other_cpu_peak_pct": None, "quiet": False}])
    blind["other_load"]["other_cpu_peak_pct"] = None

    assert check_load_record.summary_lines(blind)[0].startswith("OTHER LOAD NOT MEASURED")
    assert check_load_record.summary_lines(_fake_result(time.time(), []))[0].startswith("2 checks; slowest")


class _Machine:
    """A machine and its clock: other load and a headless browser process in each second that *loaded(second)* says."""

    available, now = True, 0.0

    def __init__(self, loaded) -> None:
        self.loaded = loaded

    def read(self) -> Reading:
        busy = self.loaded(self.now)
        return Reading(self.now, 1.0, 60.0 if busy else 3.0, 1 if busy else 0)

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _wait(loaded, limit_s: float) -> tuple[dict[str, Any], list[str]]:
    machine, said = _Machine(loaded), []
    clock = lambda: machine.now  # noqa: E731
    waited = check_load_machine.wait_quiet(machine, limit_s, clock=clock, sleep=machine.sleep, say=said.append)
    return waited, said


def test_the_run_waits_for_sixty_quiet_seconds_in_a_row_before_it_starts() -> None:
    waited, said = _wait(lambda second: second <= 30 or second == 50, 600)

    assert waited == {"limit_s": 600, "need_s": 60.0, "waited_s": 110.0, "got_quiet": True, "measured": True}
    assert len(said) == 1 and "1 min" in said[0] and "quiet for 10 of the 60 s" in said[0], "a line each minute"


def test_the_run_gives_up_waiting_starts_anyway_and_the_summary_says_it_never_got_quiet() -> None:
    waited, said = _wait(lambda second: True, 150)

    assert waited["got_quiet"] is False and waited["waited_s"] == 150.0 and len(said) == 2
    assert "60.0% of the CPU" in said[0] and "1 headless browser" in said[0]
    lines = check_load_record.summary_lines(_result([_entry("load-d-1", 3.0, 0)], waited))
    assert lines[0].startswith("NEVER GOT QUIET") and "150 s" in lines[0]


def _slow(execution_id: str, *, files: list[str] | None = None) -> check.Checked:
    time.sleep(0.3)
    return check.Checked(check.PASSED, "checked")


def test_a_load_run_records_each_checks_other_load_and_still_removes_every_copy(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    made, removed = _install(tmp_path, monkeypatch, _slow)
    loaded = SimpleNamespace(available=True, own_from="job", read=lambda: Reading(time.time(), 1.0, 60.0, 3))

    result = check_load.run_load(tmp_path, tmp_path / "c", [("thomas/right.py", 31)] * 2, stamp="q1",
                                 wait_quiet_s=0.2, sampler=loaded)  # fmt: skip

    assert len(made) == 2 and sorted(removed) == sorted(made) and result["copies_left"] == []
    assert result["wait_quiet"]["got_quiet"] is False and result["quiet"] is False
    for entry in result["checks"]:
        assert (entry["other_cpu_peak_pct"], entry["quiet"]) == (60.0, False)
        assert entry["headless_browser_processes_max"] == 3
        assert entry["free_disk_min_bytes"] > 0 and entry["disk_peak_bytes"] >= 0, "the disk figures are unchanged"
    assert result["other_load"]["own_cpu_from"] == "job" and result["other_load"]["readings"] >= 2
    printed = "\n".join(check_load.summary_lines(result))
    assert "NEVER GOT QUIET" in printed and "load-q1-1" in printed and "load-q1-2" in printed
    capsys.readouterr()


def test_main_hands_wait_quiet_to_the_run_and_refuses_a_negative_one(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(check.CHECK_ENV, raising=False)
    monkeypatch.setattr(check_load, "pick_modules", lambda blue, **kwargs: [("thomas/a.py", 25)] * 2)
    asked: list[float] = []

    def run(*args: Any, wait_quiet_s: float = 0.0, **kwargs: Any) -> dict[str, Any]:
        asked.append(wait_quiet_s)
        return {**_fake_result(time.time(), []), **_result([_entry("load-t7-1", 70.0, 4)])}

    monkeypatch.setattr(check_load, "run_load", run)
    argv = ["--count", "2", "--blue", str(tmp_path), "--out-dir", str(tmp_path / "out"), "--wait-quiet", "600"]

    assert check_load.main(argv) == 0 and asked == [600.0]
    assert "NOT QUIET" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        check_load.main([*argv[:-1], "-1"])
    capsys.readouterr()


def test_the_real_sampler_reads_this_processs_own_cpu() -> None:
    psutil = pytest.importorskip("psutil")
    sampler = check_load_machine.Sampler(psutil_mod=psutil, job_cpu=lambda: None)
    pids, before = sampler.own()

    end = time.process_time() + 0.2
    while time.process_time() < end:
        pass
    after = sampler.own()[1]

    assert os.getpid() in pids and after - before >= 0.15
    busy, total = check_load_machine._busy_total(psutil.cpu_times())
    assert 0.0 <= busy <= total
