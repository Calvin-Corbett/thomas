"""Observe project preparation without imposing a deadline or an inactivity limit."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from thomas.server import green_checkout

log = logging.getLogger(__name__)


class Progress:
    """The current preparation stage, for reporting while the start waits."""

    def __init__(self) -> None:
        self.stage = "getting ready"
        self.last = time.monotonic()

    def touch(self, stage: str | None = None) -> None:
        if stage:
            self.stage = stage
        self.last = time.monotonic()


def files_under(*roots: Path) -> int:
    """How many files exist under these folders now; a folder that is mid-change counts what it can."""
    total = 0
    pending = [str(root) for root in roots]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
                    else:
                        total += 1
        except OSError:
            continue
    return total


async def watch_copy(execution_id: str, progress: Progress, poll_s: float) -> None:
    """While the green is being written, a growing file count is progress (the checkout is one silent git call)."""
    try:
        work, git_dir = green_checkout._paths(execution_id)
    except green_checkout.GreenUnavailable:
        return
    seen = 0
    while True:
        await asyncio.sleep(poll_s)
        count = await asyncio.to_thread(files_under, work, git_dir)
        if count > seen:
            seen = count
            progress.touch()


async def wait_for_preparation(task: asyncio.Task[Any], progress: Progress, poll_s: float) -> Any:
    """Wait for completion or a real fault; polling only reports elapsed time, never cancels the work."""
    began = time.monotonic()
    while True:
        done, _ = await asyncio.wait({task}, timeout=poll_s)
        if done:
            return task.result()
        log.info("Preparing Thomas project: %.1f seconds elapsed while %s", time.monotonic() - began, progress.stage)
