"""The scheduler lets go of its lock file when the app that installed it shuts down (2026-09-05).

codex's finding: every chat API test reached TemporaryDirectory cleanup with
.thomas/schedules.json.lock still held (WinError 32). Two causes: nothing
stopped the scheduler on app cleanup, and installing a scheduler for another
data dir abandoned the previous one with its lock and polling thread.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from aiohttp import web

from thomas.core import scheduler as sched_mod
from thomas.core.schedule_executor import install_scheduler, schedule_file


def _held(path: Path) -> bool:
    """True while another handle holds the lock file (Windows refuses the delete; elsewhere try to relock)."""
    lock = path.with_suffix(path.suffix + ".lock")
    if not lock.exists():
        return False
    try:
        lock.unlink()
    except OSError:
        return True
    return False


def test_installing_for_another_data_dir_stops_the_previous_scheduler(tmp_path: Path) -> None:
    first_dir, second_dir = tmp_path / "a", tmp_path / "b"
    first = install_scheduler(data_dir=first_dir, auto_start=True)
    assert first._instance_lock_acquired is True
    assert _held(schedule_file(first_dir)) is True

    second = install_scheduler(data_dir=second_dir, auto_start=True)
    assert second is not first
    assert first._instance_lock_acquired is False
    assert _held(schedule_file(first_dir)) is False
    second.stop()
    sched_mod._SCHED = None


def test_app_cleanup_stops_the_scheduler_and_frees_the_lock(tmp_path: Path) -> None:
    app = web.Application()
    sched = install_scheduler(data_dir=tmp_path, auto_start=True, app=app)
    assert sched._instance_lock_acquired is True

    async def scenario():
        runner = web.AppRunner(app)
        await runner.setup()
        await runner.cleanup()

    asyncio.run(scenario())
    assert sched._instance_lock_acquired is False
    assert _held(schedule_file(tmp_path)) is False
    assert sched_mod._SCHED is None
    shutil.rmtree(tmp_path / ".thomas", ignore_errors=False)
