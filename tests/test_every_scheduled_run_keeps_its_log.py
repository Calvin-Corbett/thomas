"""Each scheduled run keeps its own log, even when timestamps and slugs collide."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.core import schedule_executor


@pytest.fixture
def fixed_clock(monkeypatch) -> None:
    def fixed(fmt: str) -> str:
        if fmt == "%Y%m%d-%H%M%S":
            return "20261009-120000"
        return "2026-10-09 12:00:00"

    monkeypatch.setattr(schedule_executor, "time", SimpleNamespace(strftime=fixed, time=time.time))


def _done(output: str, *, returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=output, stderr=stderr)


def test_two_runs_of_the_same_goal_keep_both_outputs(tmp_path: Path, monkeypatch, fixed_clock) -> None:
    outputs = iter(("first run output", "second run output"))
    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", lambda *args, **kwargs: _done(next(outputs)))
    execute = schedule_executor.make_subprocess_executor(log_dir=tmp_path)

    execute("Summarise my inbox", "default")
    execute("Summarise my inbox", "default")

    logs = list(tmp_path.glob("*.log"))
    assert len(logs) == 2
    assert any("first run output" in log.read_text(encoding="utf-8") for log in logs)
    assert any("second run output" in log.read_text(encoding="utf-8") for log in logs)


def test_failed_run_still_has_its_log_after_success(tmp_path: Path, monkeypatch, fixed_clock) -> None:
    results = iter((_done("", returncode=2, stderr="boom"), _done("success")))
    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", lambda *args, **kwargs: next(results))
    execute = schedule_executor.make_subprocess_executor(log_dir=tmp_path)

    with pytest.raises(RuntimeError) as caught:
        execute("Summarise my inbox", "default")
    failed_log = Path(str(caught.value).rsplit("see ", 1)[1])
    execute("Summarise my inbox", "default")

    assert len(list(tmp_path.glob("*.log"))) == 2
    assert "boom" in failed_log.read_text(encoding="utf-8")


def test_timed_out_run_still_has_its_log_after_success(tmp_path: Path, monkeypatch, fixed_clock) -> None:
    calls = iter((subprocess.TimeoutExpired(["python"], 5, output="partial"), _done("success")))

    def fake_run(*args, **kwargs):
        result = next(calls)
        if isinstance(result, subprocess.TimeoutExpired):
            raise result
        return result

    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", fake_run)
    execute = schedule_executor.make_subprocess_executor(log_dir=tmp_path, timeout_s=5)

    with pytest.raises(RuntimeError) as caught:
        execute("Summarise my inbox", "default")
    timed_out_log = Path(str(caught.value).rsplit("see ", 1)[1])
    execute("Summarise my inbox", "default")

    assert len(list(tmp_path.glob("*.log"))) == 2
    assert "partial" in timed_out_log.read_text(encoding="utf-8")


def test_goals_with_the_same_first_40_slug_characters_keep_both_logs(tmp_path: Path, monkeypatch, fixed_clock) -> None:
    outputs = iter(("first run output", "second run output"))
    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", lambda *args, **kwargs: _done(next(outputs)))
    execute = schedule_executor.make_subprocess_executor(log_dir=tmp_path)

    execute("Summarise my inbox and draft replies to everyone in it", "default")
    execute("Summarise my inbox and draft replies to everyone else", "default")

    logs = list(tmp_path.glob("*.log"))
    assert len(logs) == 2
    assert (tmp_path / "20261009-120000-Summarise-my-inbox-and-draft-replies-to--2.log").exists()
    assert any("first run output" in log.read_text(encoding="utf-8") for log in logs)
    assert any("second run output" in log.read_text(encoding="utf-8") for log in logs)


def test_eight_threads_keep_eight_distinct_outputs(tmp_path: Path, monkeypatch, fixed_clock) -> None:
    lock = threading.Lock()
    outputs: list[str] = []
    errors: list[BaseException] = []

    def fake_run(*args, **kwargs):
        with lock:
            text = f"output from call {len(outputs)}"
            outputs.append(text)
        return _done(text)

    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", fake_run)
    execute = schedule_executor.make_subprocess_executor(log_dir=tmp_path)

    def run() -> None:
        try:
            execute("Summarise my inbox", "default")
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    logs = list(tmp_path.glob("*.log"))
    assert len(logs) == 8
    assert {log.read_text(encoding="utf-8").split("--- stdout ---\n", 1)[1].split("\n", 1)[0] for log in logs} == set(
        outputs
    )


def test_could_not_start_writes_a_log_and_propagates_oserror(tmp_path: Path, monkeypatch, fixed_clock) -> None:
    def fake_run(*args, **kwargs):
        raise OSError("cannot start")

    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", fake_run)
    execute = schedule_executor.make_subprocess_executor(log_dir=tmp_path)

    with pytest.raises(OSError, match="cannot start"):
        execute("Summarise my inbox", "default")

    logs = list(tmp_path.glob("*.log"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert "goal: Summarise my inbox" in text
    assert "exit: could not start: OSError: cannot start" in text


def test_first_run_keeps_the_original_readable_name(tmp_path: Path, monkeypatch, fixed_clock) -> None:
    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", lambda *args, **kwargs: _done("done"))
    schedule_executor.make_subprocess_executor(log_dir=tmp_path)("Summarise my inbox", "default")

    assert [log.name for log in tmp_path.glob("*.log")] == ["20261009-120000-Summarise-my-inbox.log"]
