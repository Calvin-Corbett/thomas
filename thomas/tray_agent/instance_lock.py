"""One tray agent per port: an OS-level lock held for as long as the process lives.

Unlike a pid file, the lock cannot go stale. Windows and POSIX both drop it when
the holding process dies, so a crashed tray never blocks the next one.
"""

from __future__ import annotations

import errno
import logging
import os
from pathlib import Path
from typing import BinaryIO

log = logging.getLogger(__name__)

# What a lock that someone else holds looks like: msvcrt.locking raises EACCES,
# flock raises EAGAIN (EACCES on some systems).
_CONTENDED = frozenset({errno.EACCES, errno.EAGAIN, errno.EDEADLK})


def _lock_first_byte(fh: BinaryIO) -> None:
    fh.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_first_byte(fh: BinaryIO) -> None:
    fh.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class InstanceLock:
    """Non-blocking exclusive lock on the first byte of ``path``."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: BinaryIO | None = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    def acquire(self) -> bool:
        """Take the lock. False only when another live process holds it.

        A lock that cannot be taken for any other reason (an unwritable profile
        folder, a filesystem that refuses locks) is not a duplicate agent, so the
        caller runs without it: the lock may only block a start it has proven is one.
        """
        if self._fh is not None:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self.path, "a+b")
        except OSError as exc:
            log.warning("Tray agent lock %s unavailable (%s); running without it.", self.path, exc)
            return True
        try:
            _lock_first_byte(fh)
        except OSError as exc:
            fh.close()
            if exc.errno in _CONTENDED:
                return False
            log.warning("Tray agent lock %s could not be taken (%s); running without it.", self.path, exc)
            return True
        self._fh = fh
        return True

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            _unlock_first_byte(fh)
        except OSError:
            pass  # closing the handle drops the lock anyway
        fh.close()
