"""A worker waiting for the owner is not a stuck worker.

Observed 2026-09-22: on Autopilot, Thomas's self-development worker reached a
protected file, and the password prompt opened on your screen. The worker's
watchdog counts seconds since the last progress event, and after 135 of them it
failed the task ("provider-native worker produced no further progress") while
the prompt was still open and waiting for you. The prompt you were about to
answer belonged to a task that had already been given up.

Anything that stops to wait for the person -- a password prompt, a question card
-- wraps the wait in :func:`awaiting_owner`. The watchdogs read
:func:`seconds_since_owner_wait` and measure staleness from whichever is more
recent: the last progress event, or the moment the owner last answered.
Answering does not restart a cold clock -- a worker that was waiting on you
gets its full grace period again from the moment you answer.

Process-wide on purpose. Only one prompt is open at a time, and a prompt names
what it is for, so the cost -- other workers' clocks also pause while you are
answering -- is bounded by how long you take, and it errs toward not killing
work you are in the middle of approving.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

_lock = threading.Lock()
_open = 0
_last_released: float | None = None


@contextmanager
def awaiting_owner() -> Iterator[None]:
    """Mark the enclosed block as waiting for the person, not stuck."""
    global _open, _last_released
    with _lock:
        _open += 1
    try:
        yield
    finally:
        with _lock:
            _open -= 1
            _last_released = time.monotonic()


def seconds_since_owner_wait() -> float | None:
    """0 while anything is waiting on the owner; seconds since the last wait
    ended otherwise; None if nothing has waited on the owner in this process."""
    with _lock:
        if _open > 0:
            return 0.0
        if _last_released is None:
            return None
        return max(0.0, time.monotonic() - _last_released)


def reset() -> None:
    """For tests."""
    global _open, _last_released
    with _lock:
        _open = 0
        _last_released = None


__all__ = ["awaiting_owner", "reset", "seconds_since_owner_wait"]
