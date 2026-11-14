"""A Thomas project's commands may stop only the processes that project started.

Measured 2026-09-27: every Thomas project's commands run as thomas-agent. One project's team, cleaning up after its own
checks, listed every python process on the machine whose command line held "pytest" or "thomas" and ran
`taskkill /PID ... /F` on the list. The same account owns every other project's test runs and this runner, so nothing
stopped it; the one process it could not stop belonged to another account. The runner keeps each project's processes
in a job of their own, so it knows which are that project's: a command that stops processes must name them by id, and
every id must be in the project's job.

The by-name probes use an image name no process has, so a broken guard stops nothing on this machine.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

import pytest
from scripts.cage import process_guard, shell_runner

NOBODY = "thomas-guard-probe-nobody"  # an image name no process has
windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")


def test_a_stop_by_id_names_its_targets() -> None:
    assert process_guard.stops("taskkill /PID 11 /PID 12 /F") == process_guard.Stop(frozenset({11, 12}), "")
    assert process_guard.stops('powershell -Command "Stop-Process -Id 5,6 -Force"').ids == {5, 6}
    assert process_guard.stops('powershell -Command "kill 7"').ids == {7}


@pytest.mark.parametrize(
    "command",
    [
        f"taskkill /F /IM {NOBODY}.exe",
        'taskkill /F /FI "IMAGENAME eq python.exe"',
        "for /f %p in (pids.txt) do taskkill /PID %p /F",
        'powershell -Command "Get-Process python | Stop-Process -Force"',
        f'powershell -Command "Stop-Process -Name {NOBODY}"',
        "wmic process where name='python.exe' delete",
        'powershell -Command "Get-CimInstance Win32_Process | Invoke-CimMethod -MethodName Terminate"',
    ],
)
def test_a_stop_whose_targets_are_found_while_it_runs_cannot_be_checked(command: str) -> None:
    stop = process_guard.stops(command)
    assert stop is not None and stop.unscoped, command


@pytest.mark.parametrize(
    "command",
    ["git status", 'rg -n "taskkill" scripts', "python -m pytest -q", 'git grep -n "Stop-Process"'],
)
def test_a_command_that_stops_nothing_is_not_a_stop(command: str) -> None:
    assert process_guard.stops(command) is None


def _alive(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong(0)
        kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def _start_sleeper(work: Path) -> int:
    marker = work / "sleeper.pid"
    sleeper = (
        f"\"{sys.executable}\" -c \"import os,time; open('sleeper.pid','w').write(str(os.getpid())); time.sleep(60)\""
    )
    started = shell_runner.run_command({"id": "s", "command": f'start "" /b {sleeper}', "cwd": str(work)})
    assert started["outcome"] == "ok"
    deadline = time.time() + 10
    while time.time() < deadline:
        if marker.exists() and marker.read_text().strip():
            return int(marker.read_text().strip())
        time.sleep(0.1)
    raise AssertionError("the sleeper never wrote its pid")


@pytest.fixture
def greens(tmp_path: Path):
    made: list[str] = []

    def make(name: str) -> Path:
        work = tmp_path / "green" / "work" / name
        work.mkdir(parents=True)
        made.append(name)
        return work

    yield make
    for name in made:
        shell_runner.run_command({"id": "end", "action": "end_green", "green": name})


@windows_only
def test_a_project_can_stop_a_process_it_started(greens) -> None:
    work = greens("exec-guard-own")
    pid = _start_sleeper(work)

    stopped = shell_runner.run_command({"id": "k", "command": f"taskkill /PID {pid} /F", "cwd": str(work)})

    assert stopped["outcome"] == "ok" and stopped["returncode"] == 0, stopped["output"]
    deadline = time.time() + 5
    while _alive(pid) and time.time() < deadline:
        time.sleep(0.1)
    assert not _alive(pid)


@windows_only
def test_a_project_cannot_stop_another_projects_process(greens) -> None:
    theirs = _start_sleeper(greens("exec-guard-theirs"))
    mine_work = greens("exec-guard-mine")
    mine = _start_sleeper(mine_work)

    refused = shell_runner.run_command({"id": "k", "command": f"taskkill /PID {theirs} /F", "cwd": str(mine_work)})

    assert refused["outcome"] == "invalid", refused["output"]
    assert str(theirs) in refused["output"] and "did not start" in refused["output"]
    assert str(mine) in refused["output"]  # the refusal lists this project's own processes
    assert _alive(theirs)


@windows_only
def test_a_project_cannot_stop_processes_by_name(greens) -> None:
    work = greens("exec-guard-name")

    for command in (f"taskkill /F /IM {NOBODY}.exe", f'powershell -NoProfile -Command "Stop-Process -Name {NOBODY}"'):
        refused = shell_runner.run_command({"id": "n", "command": command, "cwd": str(work)})
        assert refused["outcome"] == "invalid", (command, refused["output"])
        assert "by id" in refused["output"]


@windows_only
def test_a_command_outside_a_project_is_not_checked(tmp_path: Path) -> None:
    ran = shell_runner.run_command({"id": "o", "command": f"taskkill /F /IM {NOBODY}.exe", "cwd": str(tmp_path)})

    assert ran["outcome"] == "ok"  # taskkill itself answers that no such process runs
