"""A scheduled task actually runs when it fires.

Nothing in the package ever handed ``TaskScheduler`` an executor: every task
saved by ``thomas cron add`` was stored and never run. When a task fires it
now runs as a headless Thomas chat in its own process and leaves a log.
"""

from __future__ import annotations

import sys
from pathlib import Path

from thomas.core.schedule_executor import make_subprocess_executor


def test_a_fired_task_runs_headless_thomas_and_writes_a_log(tmp_path: Path, monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        seen.append(list(cmd))

        class _Done:
            returncode = 0
            stdout = "Thomas: done. Summary: inbox is empty."
            stderr = ""

        return _Done()

    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", fake_run)
    execute = make_subprocess_executor(log_dir=tmp_path / "logs", timeout_s=30)

    execute("Summarise my inbox", "default")

    assert seen and seen[0][:3] == [sys.executable, "-m", "thomas.cli.headless_run"]
    assert "Summarise my inbox" in seen[0]
    logs = list((tmp_path / "logs").glob("*.log"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert "Summarise my inbox" in text and "inbox is empty" in text and "exit 0" in text


def test_a_failed_run_is_logged_and_raised_so_the_scheduler_records_the_error(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):  # noqa: ANN001
        class _Done:
            returncode = 2
            stdout = ""
            stderr = "boom"

        return _Done()

    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", fake_run)
    execute = make_subprocess_executor(log_dir=tmp_path / "logs", timeout_s=30)

    try:
        execute("do it", "default")
        raised = False
    except RuntimeError as exc:
        raised = "exit 2" in str(exc)
    assert raised
    assert "boom" in next((tmp_path / "logs").glob("*.log")).read_text(encoding="utf-8")


def test_the_server_gives_the_scheduler_an_executor(tmp_path: Path, monkeypatch) -> None:
    from thomas.core import scheduler as sched_mod
    from thomas.core.schedule_executor import install_scheduler

    monkeypatch.setattr(sched_mod, "_SCHED", None)
    sched = install_scheduler(data_dir=tmp_path, auto_start=False)
    try:
        assert sched is sched_mod.get_scheduler()
        assert sched._execute_fn.__name__ == "run_scheduled_task"
        assert str(sched._path).startswith(str(tmp_path))
    finally:
        sched.stop()
        monkeypatch.setattr(sched_mod, "_SCHED", None)
