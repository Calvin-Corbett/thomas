"""What a scheduled task does when it fires: run as a headless Thomas chat and keep a log.

``TaskScheduler`` needs an ``execute_fn(goal_text, channel)``. Until
2026-09-05 nothing in the package supplied one: ``thomas cron add`` saved
tasks that could never run. This module supplies it and installs one
scheduler, on one file under the data dir, for the server and the CLI alike.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas.core.atomic_json import read_text_with_retry, write_json_atomic
from thomas.core.pause import paused
from thomas.core.scheduler import ScheduledTask, TaskScheduler

DEFAULT_TIMEOUT_S = 30 * 60.0

# Held from a read of the list to the write that follows it, so a save by the other scheduler in this process cannot land
# in between and be lost.
_SAVING = threading.Lock()


def schedule_file(data_dir: Path) -> Path:
    return Path(data_dir) / ".thomas" / "schedules.json"


def schedule_log_dir(data_dir: Path) -> Path:
    return Path(data_dir) / ".thomas" / "schedule_logs"


def _new_log_path(log_root: Path, goal_text: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(goal_text)).strip("-")[:40] or "task"
    stem = f"{stamp}-{slug}"
    for attempt in range(1, 1001):
        suffix = "" if attempt == 1 else f"-{attempt}"
        path = log_root / f"{stem}{suffix}.log"
        try:
            with path.open("x", encoding="utf-8"):
                pass
        except FileExistsError:
            continue
        return path
    raise OSError(f"could not reserve a scheduled task log after 1000 tries: {log_root / stem}")


def make_subprocess_executor(*, log_dir: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> Callable[[str, str], None]:
    log_root = Path(log_dir)

    def run_scheduled_task(goal_text: str, channel: str) -> None:
        log_root.mkdir(parents=True, exist_ok=True)
        log_path = _new_log_path(log_root, goal_text)
        # thomas.cli.headless_run registers the ChatGPT sign-in before chat;
        # plain `thomas chat` cannot use it (found when the first task fired).
        cmd = [sys.executable, "-m", "thomas.cli.headless_run", str(goal_text)]
        env = {**os.environ, "THOMAS_SCHEDULED_TASK": "1", "THOMAS_SCHEDULED_CHANNEL": str(channel or "default")}
        started = time.time()
        header = [f"goal: {goal_text}", f"channel: {channel}", f"started: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=env, check=False)
        except subprocess.TimeoutExpired as exc:
            log_path.write_text(
                "\n".join(header + [f"exit: timeout after {timeout_s:g}s", "", str(exc.stdout or "")]),
                encoding="utf-8",
            )
            raise RuntimeError(f"scheduled task timed out after {timeout_s:g}s: see {log_path}") from exc
        except Exception as exc:
            # Broad catch: subprocess.run can fail before returning with many exception types.
            logging.getLogger(__name__).exception("scheduled task subprocess could not start")
            log_path.write_text(
                "\n".join(header + [f"exit: could not start: {type(exc).__name__}: {exc}"]), encoding="utf-8"
            )
            raise
        elapsed = time.time() - started
        body = header + [
            f"exit {proc.returncode} after {elapsed:.1f}s",
            "",
            "--- stdout ---",
            str(proc.stdout or ""),
            "--- stderr ---",
            str(proc.stderr or ""),
        ]
        log_path.write_text("\n".join(body), encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(f"scheduled task ended with exit {proc.returncode}: see {log_path}")

    return run_scheduled_task


def _add_latest_runs(path: Path, tasks: dict[str, ScheduledTask]) -> None:
    """Add each task's latest run to the file as it stands, if the file lacks it, and change nothing else there.

    A task that has gone stays gone. A file that cannot be read is left alone, because saving over it would lose a whole
    list for one line of history.
    """
    try:
        saved = json.loads(read_text_with_retry(path))
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).warning("Left %s as it is: could not read it to add a finished run: %s", path, exc)
        return
    listed = saved.get("tasks") if isinstance(saved, dict) else None
    changed = False
    for item in listed if isinstance(listed, list) else []:
        task = tasks.get(item.get("id")) if isinstance(item, dict) else None
        run = task.run_history[-1] if task and task.run_history else None
        if run is None or run in (item.get("run_history") or []):
            continue
        item["run_history"] = [*(item.get("run_history") or []), run][-30:]
        if not run["ok"]:
            item["last_error"] = run["error"]
        item["updated_at"] = run["finished_at"]
        changed = True
    if changed:
        write_json_atomic(path, saved)


class SharedFileScheduler(TaskScheduler):
    """A scheduler that shares its file, so once stopped it saves only the runs that end after that.

    A run outlives a stop, and by the time it ends ``thomas cron`` may have changed the file from a process of its own,
    and a new scheduler may have taken over from this one. Saving this copy of the list then would undo all of that: a
    task added would go, and a task removed would come back.
    """

    _stopped = False

    def stop(self) -> None:
        super().stop()
        # Only now: the thread can be part way through a pass, and that pass has to reach the file.
        self._stopped = True

    def _poll_once(self) -> None:
        """While Thomas is paused nothing is started, and a task that falls due waits: it runs when you resume."""
        if paused():
            return
        super()._poll_once()

    def _persist_locked(self) -> None:
        with _SAVING:
            if self._stopped:
                _add_latest_runs(self._path, self._tasks)
            else:
                super()._persist_locked()


def install_scheduler(
    *,
    data_dir: Path,
    auto_start: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    app: Any = None,
) -> Any:
    """Create the process-wide scheduler on the data-dir file with a real executor.

    Idempotent: a scheduler already installed on the same file is returned as is.
    A scheduler installed for a different file is stopped first, so its polling
    thread and its lock file do not outlive the data dir that owned them. With
    an aiohttp ``app``, the scheduler stops on the app's cleanup (codex found
    every chat API test holding .thomas/schedules.json.lock at temp-dir
    cleanup, 2026-09-05).
    """
    from thomas.core import scheduler as sched_mod

    path = schedule_file(data_dir)
    with sched_mod._SCHED_LOCK:
        existing = sched_mod._SCHED
        if existing is not None and Path(getattr(existing, "_path", "")) == path:
            sched = existing
        else:
            if existing is not None:
                existing.stop()
            sched = SharedFileScheduler(
                execute_fn=make_subprocess_executor(log_dir=schedule_log_dir(data_dir), timeout_s=timeout_s),
                schedule_path=path,
                auto_start=auto_start,
            )
            sched_mod._SCHED = sched
    if app is not None:

        async def _stop_scheduler(_app: Any) -> None:
            sched.stop()
            with sched_mod._SCHED_LOCK:
                if sched_mod._SCHED is sched:
                    sched_mod._SCHED = None

        app.on_cleanup.append(_stop_scheduler)
    return sched


__all__ = ["SharedFileScheduler", "install_scheduler", "make_subprocess_executor", "schedule_file", "schedule_log_dir"]
