"""A failed check joins its reviewer without waiting out a useless CLI run."""

from __future__ import annotations

import contextvars
import io
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from thomas.server.precard import review, review_dial, review_job


def test_cancelled_review_reaps_its_process(tmp_path):
    ready = tmp_path / "ready"
    command = [
        sys.executable,
        "-c",
        "import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(60)",
        str(ready),
    ]
    with review_job.cancellable() as cancel, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            contextvars.copy_context().run,
            review_job.run,
            subprocess.run,
            command,
            cwd=str(tmp_path),
            timeout=60,
        )
        try:
            assert _wait_for(ready), "reviewer did not start"
            cancel.set()
            with pytest.raises(review_job.Cancelled):
                future.result(timeout=5)
        finally:
            cancel.set()


def _wait_for(path):
    import time

    until = time.monotonic() + 5
    while time.monotonic() < until:
        if path.is_file():
            return True
        time.sleep(0.01)
    return False


@pytest.mark.parametrize("text", [False, True])
def test_cancellable_review_keeps_successful_output(tmp_path, text):
    with review_job.cancellable():
        done = review_job.run(
            subprocess.run,
            [sys.executable, "-c", "import sys; print(sys.stdin.read()); print('err', file=sys.stderr)"],
            input="prompt" if text else b"prompt",
            text=text,
            cwd=tmp_path,
            timeout=10,
        )
    assert done.returncode == 0
    assert done.stdout == ("prompt\n" if text else b"prompt\r\n" if sys.platform == "win32" else b"prompt\n")
    assert done.stderr == ("err\n" if text else b"err\r\n" if sys.platform == "win32" else b"err\n")


def test_completed_reviewer_does_not_wait_for_descendant_output_handles(tmp_path):
    release = tmp_path / "release"
    child = (
        "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); end=time.monotonic()+15; "
        "\nwhile not p.exists() and time.monotonic()<end: time.sleep(.02)"
    )
    parent = "import subprocess,sys; subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); print('done')"
    try:
        with review_job.cancellable():
            done = review_job.run(
                subprocess.run,
                [sys.executable, "-c", parent, child, str(release)],
                timeout=5,
            )
        assert done.returncode == 0
        assert done.stdout.strip() == b"done"
    finally:
        release.touch()


def test_cancelled_review_does_not_wait_forever_for_inherited_pipes(monkeypatch):
    class PipesHeld:
        def __init__(self):
            self.stdin, self.stdout, self.stderr = (io.BytesIO() for _ in range(3))
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def poll(self):
            return 0

        def communicate(self, input=None, timeout=None):
            self.calls.append(timeout)
            if timeout is None:
                pytest.fail("cancellation attempted an unbounded pipe drain")
            cancel.set()
            raise subprocess.TimeoutExpired("reviewer", timeout)

    process = PipesHeld()
    monkeypatch.setattr(review_job.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(review_job, "_stop", lambda proc: None)
    monkeypatch.setattr(
        review_job.contained_process, "OwnedWindowsJob", lambda proc: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(review_job.contained_process, "_resume", lambda proc: None)
    with review_job.cancellable() as cancel, pytest.raises(review_job.Cancelled):
        review_job.run(subprocess.run, ["reviewer"], timeout=60)
    assert len(process.calls) == 2
    assert all(stream.closed for stream in (process.stdin, process.stdout, process.stderr))


def test_output_handles_cannot_be_held_open_as_pipes(tmp_path, monkeypatch):
    popen = review_job.subprocess.Popen
    seen = []

    def recorded(*args, **kwargs):
        seen.append((kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]))
        return popen(*args, **kwargs)

    monkeypatch.setattr(
        review_job,
        "subprocess",
        SimpleNamespace(
            Popen=recorded,
            PIPE=subprocess.PIPE,
            TimeoutExpired=subprocess.TimeoutExpired,
            CompletedProcess=subprocess.CompletedProcess,
        ),
    )
    with review_job.cancellable():
        done = review_job.run(subprocess.run, [sys.executable, "-c", "print('ok')"], cwd=tmp_path, timeout=10)
    assert done.stdout.strip() == b"ok"
    assert all(handle != subprocess.PIPE for pair in seen for handle in pair)


def test_exited_posix_reviewer_still_stops_its_process_group(monkeypatch):
    if sys.platform == "win32":
        pytest.skip("POSIX process groups")
    stopped = []
    process = type("Exited", (), {"pid": 12345, "poll": lambda self: 0})()
    monkeypatch.setattr(review_job.os, "killpg", lambda pid, sig: stopped.append(pid))
    review_job._stop(process)
    assert stopped == [process.pid]


def test_cancellation_does_not_wait_for_an_unread_prompt(tmp_path):
    ready = tmp_path / "ready"
    command = [
        sys.executable,
        "-c",
        "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); time.sleep(60)",
        str(ready),
    ]
    with review_job.cancellable() as cancel, ThreadPoolExecutor(max_workers=1) as executor:
        context = contextvars.copy_context()
        future = executor.submit(
            context.run, review_job.run, subprocess.run, command,
            cwd=str(tmp_path), input=b"x" * 2_000_000, timeout=10,
        )  # fmt: skip
        try:
            for _ in range(400):
                if ready.exists() or future.done():
                    break
                threading.Event().wait(0.01)
            assert ready.exists(), future.result() if future.done() else "reviewer did not start"
            cancel.set()
            with pytest.raises(review_job.Cancelled):
                future.result(timeout=4)
        finally:
            cancel.set()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job owns descendants after their launcher exits")
def test_completed_windows_launcher_leaves_no_review_descendant(tmp_path):
    import psutil

    child_pid = tmp_path / "child_pid"
    parent = (
        "import pathlib,subprocess,sys; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid))"
    )
    with review_job.cancellable():
        done = review_job.run(subprocess.run, [sys.executable, "-c", parent, str(child_pid)], cwd=tmp_path, timeout=10)
    assert done.returncode == 0
    pid = int(child_pid.read_text())
    try:
        psutil.Process(pid).wait(timeout=4)
    except psutil.NoSuchProcess:
        pass
    assert not psutil.pid_exists(pid)


def test_cancelled_review_never_enters_the_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(review_dial.green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(review_dial, "_still_on", lambda: None)
    entered = []

    def admitted(*args, **kwargs):
        entered.append(True)
        raise AssertionError("cancelled review asked for a turn")

    monkeypatch.setattr(review_dial.capacity_ledger, "admitted", admitted)
    with review_job.cancellable() as cancel:
        cancel.set()
        with pytest.raises(review_job.Cancelled), review_dial.turn():
            pass
    assert entered == []


def test_no_job_keeps_the_existing_subprocess_boundary(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"ok", b"")

    monkeypatch.setattr(review_job.subprocess, "run", run)
    done = review_job.run(subprocess.run, ["review"], cwd=".", input=b"prompt", timeout=10)
    assert (done.returncode, done.stdout) == (0, b"ok")
    assert len(calls) == 1
    assert calls[0][1]["input"] == b"prompt"


def test_cancelled_job_does_not_change_other_threads():
    result = []
    with review_job.cancellable() as cancel:
        cancel.set()
        thread = threading.Thread(target=lambda: result.append(review_job.check_cancelled()))
        thread.start()
        thread.join(timeout=2)
    assert result == [None]
