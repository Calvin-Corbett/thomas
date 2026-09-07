"""A rotating log handler that keeps its records when the file is shared.

Two Thomas servers on one data dir write the same thomas.log. When the file
hits its cap while the other process holds it, Windows refuses the rename
(WinError 32); the standard handler then prints a traceback to stderr and
drops the record. The record is the point. This handler writes it to the
current file regardless, notes once why rotation was skipped, and waits before
trying to rotate again.
"""

from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler

RETRY_SECONDS = 60.0


class SharedRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler whose refused rotations lose nothing."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rotation_blocked_until = 0.0

    def shouldRollover(self, record: logging.LogRecord) -> int:  # noqa: N802 (stdlib name)
        if time.monotonic() < self._rotation_blocked_until:
            return 0
        return super().shouldRollover(record)

    def doRollover(self) -> None:  # noqa: N802 (stdlib name)
        try:
            super().doRollover()
            self._rotation_blocked_until = 0.0
        except OSError as exc:
            # The base handler closed the stream before the rename failed;
            # reopen it and write on, so no record is lost to a held file.
            self._rotation_blocked_until = time.monotonic() + RETRY_SECONDS
            if self.stream is None:
                self.stream = self._open()
            note = (
                f"log rotation skipped: {exc} (another process holds this file); "
                f"writing on and retrying in {int(RETRY_SECONDS)}s"
            )
            self.stream.write(note + self.terminator)
            self.flush()


__all__ = ["SharedRotatingFileHandler", "RETRY_SECONDS"]
