"""What a scheduled task does when it fires: run as a headless Thomas chat and keep a log.

``TaskScheduler`` needs an ``execute_fn(goal_text, channel)``. Until
2026-09-05 nothing in the package supplied one: ``thomas cron add`` saved
tasks that could never run. This module supplies it and installs one
scheduler, on one file under the data dir, for the server and the CLI alike.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 30 * 60.0


def schedule_file(data_dir: Path) -> Path:
    return Path(data_dir) / ".thomas" / "schedules.json"


def schedule_log_dir(data_dir: Path) -> Path:
    return Path(data_dir) / ".thomas" / "schedule_logs"


def make_subprocess_executor(*, log_dir: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> Callable[[str, str], None]:
    log_root = Path(log_dir)

    def run_scheduled_task(goal_text: str, channel: str) -> None:
        log_root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", str(goal_text)).strip("-")[:40] or "task"
        log_path = log_root / f"{stamp}-{slug}.log"
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
            sched = sched_mod.TaskScheduler(
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


__all__ = ["install_scheduler", "make_subprocess_executor", "schedule_file", "schedule_log_dir"]
