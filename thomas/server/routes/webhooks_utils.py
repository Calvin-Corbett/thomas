"""Utility helpers shared by webhook route modules."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Cross-process lock using a companion lock file."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt  # type: ignore

            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl  # type: ignore

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore

                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        # Releasing a lock in a finally block must not mask the original error.
        # The realistic faults are named rather than swallowed wholesale: the
        # unlock itself failing, the platform module being absent, or the handle
        # already being invalid.
        except (OSError, ImportError, ValueError, AttributeError):
            pass
        try:
            f.close()
        except (OSError, ValueError):
            pass
