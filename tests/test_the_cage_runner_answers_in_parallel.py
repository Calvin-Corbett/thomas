"""The cage's shell runner answers requests side by side, not one after another.

Measured live 2026-09-23: five self-fix workers shared the one runner, and it ran
each request to the end before it read the next. One worker's two-minute test run
held every other worker's ``git status`` until that caller gave up with "the caged
runner did not answer within 30s", and the workers spent their attempts waiting
instead of working. Now each request gets a thread of its own, up to the
machine's limit, and is claimed -- renamed to a working name -- before it runs,
so no later poll can start it a second time.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
from scripts.cage import shell_runner

_WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")


def _python(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


def _drop(inbox: Path, request_id: str, command: str, cwd: Path, *, timeout_s: float = 60) -> None:
    """Hand a request in the way the server does: written whole, then renamed in."""
    payload = {"id": request_id, "command": command, "cwd": str(cwd), "timeout_s": timeout_s}
    part = inbox / f"{request_id}.part"
    part.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(part, inbox / f"{request_id}.json")


def _seconds_until(path: Path, *, within_s: float) -> float | None:
    """How long *path* took to appear, or None if it never did."""
    began = time.monotonic()
    while time.monotonic() - began < within_s:
        if path.exists():
            return time.monotonic() - began
        time.sleep(0.01)
    return None


def _reply(outbox: Path, request_id: str) -> dict:
    return json.loads((outbox / f"{request_id}.json").read_text(encoding="utf-8"))


def _removable(folder: Path, *, within_s: float = 5.0) -> bool:
    """A folder a process still works in cannot be removed on Windows."""
    deadline = time.time() + within_s
    while time.time() < deadline:
        try:
            shutil.rmtree(folder)
            return True
        except OSError:
            time.sleep(0.2)
    return False


class _Stop(Exception):
    """Ends the serve loop from a test; serve() only survives what a request can raise."""


@pytest.fixture
def live_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The real serve loop on a tmp channel, polling fast, stopped when the test ends."""
    cage = tmp_path / "cage"
    inbox, outbox = shell_runner.channel_dirs(cage)
    stopping = threading.Event()
    real_serve_once = shell_runner.serve_once

    def poll(inbox_dir: Path, outbox_dir: Path) -> int:
        if stopping.is_set():
            raise _Stop
        return real_serve_once(inbox_dir, outbox_dir)

    monkeypatch.setattr(shell_runner, "serve_once", poll)
    monkeypatch.setattr(shell_runner, "POLL_EVERY_S", 0.02)
    monkeypatch.setenv("THOMAS_CAGE_RUNNER_WORKERS", "12")

    def run() -> None:
        with contextlib.suppress(_Stop):
            shell_runner.serve(cage)

    runner = threading.Thread(target=run, daemon=True, name="test-cage-runner")
    runner.start()
    assert _seconds_until(outbox, within_s=5) is not None, "the runner never opened its channel"
    yield inbox, outbox
    stopping.set()
    runner.join(timeout=60)


def test_a_quick_command_is_not_held_behind_a_slow_one(live_runner, tmp_path: Path) -> None:
    """The live failure: a `git status` waited out a long test run and timed out."""
    inbox, outbox = live_runner
    work = tmp_path / "work"
    work.mkdir()

    # Sorted, the slow one comes first: one after another, the quick one waits 2s.
    _drop(inbox, "1-slow", _python("import time; time.sleep(2)"), work)
    _drop(inbox, "2-quick", "echo quick", work)

    quick = _seconds_until(outbox / "2-quick.json", within_s=15)
    assert quick is not None, "the quick command was never answered"
    assert quick < 0.5, f"the quick command took {quick:.2f}s: it waited for the slow one"
    assert not (outbox / "1-slow.json").exists(), "the ruler: the slow command must still be running"
    reply = _reply(outbox, "2-quick")
    assert reply["outcome"] == "ok" and "quick" in reply["output"]
    assert _seconds_until(outbox / "1-slow.json", within_s=15) is not None


def test_ten_commands_take_as_long_as_the_longest_not_the_sum(live_runner, tmp_path: Path) -> None:
    """While these run, the loop polls about fifty times a second: each still runs once."""
    inbox, outbox = live_runner
    work = tmp_path / "work"
    work.mkdir()

    began = time.monotonic()
    for n in range(10):
        _drop(inbox, f"r{n}", _python(f"open('ran-{n}.txt', 'a').write('x'); import time; time.sleep(1)"), work)
    for n in range(10):
        assert _seconds_until(outbox / f"r{n}.json", within_s=30) is not None, f"r{n} was never answered"
    took = time.monotonic() - began

    assert took < 4, f"ten 1-second commands took {took:.1f}s; one after another takes 10s"
    for n in range(10):
        reply = _reply(outbox, f"r{n}")
        assert reply["outcome"] == "ok" and reply["returncode"] == 0, reply
        assert (work / f"ran-{n}.txt").read_text(encoding="utf-8") == "x", f"r{n} ran more than once"


def test_two_polls_at_once_run_a_request_once(tmp_path: Path) -> None:
    """A request is claimed before it runs, so a poll that overlaps another finds nothing to take.

    The same double run the single-instance lock was added for (three runners on one
    channel, 2026-09-22): reading a request, running it and deleting it afterwards lets
    a second reader start it again while it runs.
    """
    inbox, outbox = shell_runner.channel_dirs(tmp_path / "cage")
    inbox.mkdir(parents=True)
    outbox.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    _drop(inbox, "once", _python("open('ran.txt', 'a').write('x'); import time; time.sleep(1)"), work)

    polls = [threading.Thread(target=shell_runner.serve_once, args=(inbox, outbox)) for _ in range(2)]
    for poll in polls:
        poll.start()
    for poll in polls:
        poll.join(timeout=30)

    assert (work / "ran.txt").read_text(encoding="utf-8") == "x", "the request ran twice"
    assert _reply(outbox, "once")["outcome"] == "ok"
    assert not list(inbox.iterdir()), "the request was left behind in the inbox"


def test_a_request_a_stopped_runner_left_running_is_answered_and_not_run_again(tmp_path: Path) -> None:
    """A command cut off halfway may have changed things; running it again from the
    start is a guess about what is safe. Its caller gets an answer that says so."""
    cage = tmp_path / "cage"
    inbox, outbox = shell_runner.channel_dirs(cage)
    inbox.mkdir(parents=True)
    outbox.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    request = {"id": "left", "command": _python("open('ran.txt', 'a').write('x')"), "cwd": str(work)}
    (inbox / "left.working").write_text(json.dumps(request), encoding="utf-8")

    assert shell_runner.serve(cage, once=True) == 0

    assert (outbox / "left.json").exists(), "the leftover request was never answered; its caller waits it out"
    reply = _reply(outbox, "left")
    assert reply["outcome"] == "error" and reply["returncode"] == -1
    assert "not run again" in reply["output"]
    assert not (work / "ran.txt").exists(), "a command cut off halfway was run a second time"
    assert not (inbox / "left.working").exists()


def test_the_pool_is_the_machines_limit_unless_you_set_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)
    monkeypatch.delenv("THOMAS_CAGE_RUNNER_WORKERS", raising=False)
    assert shell_runner.worker_count() == 8, "with nothing measured yet, a safe default"

    (tmp_path / "machine_capacity.json").write_text(json.dumps({"limit": 31}), encoding="utf-8")
    assert shell_runner.worker_count() == 31, "the machine's measured limit"

    monkeypatch.setenv("THOMAS_CAGE_RUNNER_WORKERS", "3")
    assert shell_runner.worker_count() == 3, "your setting wins"


@pytest.mark.parametrize("data_dir", [True, False])
@pytest.mark.parametrize("profile", ["", "demo", "my profile!"])
def test_the_runner_reads_the_profile_machine_capacity_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data_dir: bool, profile: str
) -> None:
    """Kept in step by a test, because the runner imports nothing of Thomas's."""
    from thomas.core import machine_capacity

    monkeypatch.setenv("THOMAS_PROFILE", profile)
    if data_dir:
        monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    else:
        monkeypatch.delenv("THOMAS_DATA_DIR", raising=False)
    assert shell_runner.capacity_profile_path() == machine_capacity._profile_path(None)


@_WINDOWS_ONLY
def test_ending_one_green_ends_all_its_commands_and_none_of_anothers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two commands of one green start at the same moment while a third runs in another.

    Every thread now shares the map of green jobs. Without a lock, both of the first
    two could create their green's job, one job would be lost, and ending the green
    would leave that command running with green as its folder.
    """
    ours = tmp_path / "green" / "work" / "exec-ours"
    theirs = tmp_path / "green" / "work" / "exec-theirs"
    ours.mkdir(parents=True)
    theirs.mkdir(parents=True)
    real_new_job = shell_runner._new_job

    def slow_new_job(*, kill_on_close: bool) -> int:
        time.sleep(0.3)  # widen the window in which two threads could both make one green's job
        return real_new_job(kill_on_close=kill_on_close)

    monkeypatch.setattr(shell_runner, "_new_job", slow_new_job)
    background = f'start "" /b {_python("import time; time.sleep(60)")}'
    together = threading.Barrier(3)

    def start_in(folder: Path) -> None:
        together.wait(timeout=10)
        shell_runner.run_command({"id": folder.name, "command": background, "cwd": str(folder), "timeout_s": 30})

    starters = [threading.Thread(target=start_in, args=(folder,)) for folder in (ours, ours, theirs)]
    for starter in starters:
        starter.start()
    for starter in starters:
        starter.join(timeout=30)
    try:
        ended = shell_runner.run_command({"id": "end", "action": "end_green", "green": "exec-ours"})
        assert ended["outcome"] == "ok"
        assert _removable(ours), "a command of the ended green is still running"
        assert not _removable(theirs, within_s=1.0), "ending one green ended another green's command"
    finally:
        shell_runner.run_command({"id": "end-theirs", "action": "end_green", "green": "exec-theirs"})
    assert _removable(theirs)


@_WINDOWS_ONLY
def test_a_command_that_times_out_leaves_its_greens_other_commands_running(tmp_path: Path) -> None:
    """One after another, a green's commands never overlapped, so a timeout could end the
    green's whole job. Side by side, that would kill a sibling that was doing fine."""
    green = tmp_path / "green" / "work" / "exec-busy"
    tests_folder = green / "tests"
    tests_folder.mkdir(parents=True)
    background = f'start "" /b {_python("import time; time.sleep(60)")}'
    spawner = _python(
        "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "time.sleep(60)"
    )
    try:
        started = shell_runner.run_command({"id": "bg", "command": background, "cwd": str(green), "timeout_s": 30})
        assert started["outcome"] == "ok"

        stuck = shell_runner.run_command({"id": "stuck", "command": spawner, "cwd": str(tests_folder), "timeout_s": 1})

        assert stuck["outcome"] == "timeout"
        assert _removable(tests_folder), "the timed-out command, or what it started, is still running"
        assert not _removable(green, within_s=1.0), "one command's timeout ended the green's other command"
    finally:
        shell_runner.run_command({"id": "end", "action": "end_green", "green": "exec-busy"})
    assert _removable(green), "ending the green did not end the command left running in it"
