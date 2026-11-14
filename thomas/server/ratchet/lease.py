"""The ratchet's single-runner lease: a byte lock on ``<ratchet folder>/ratchet.lock`` held while a run lasts.

The same pattern as the promoter's own ``promoter.lock`` (scripts/cage/promoter_service.py): a second run of
the same account finds the lock taken and does not start. No Praxis coordinator lease exists to use instead.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import IO

log = logging.getLogger(__name__)


def _lock(handle: IO[str]) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: IO[str]) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        log.debug("ratchet lease: unlock failed; closing the handle releases it", exc_info=True)


@contextlib.contextmanager
def lease(folder: Path) -> Iterator[bool]:
    """Hold the lock for as long as the ``with`` block lasts: True when this caller holds it."""
    folder.mkdir(parents=True, exist_ok=True)
    handle = open(folder / "ratchet.lock", "a+", encoding="utf-8")  # noqa: SIM115 - held for the run
    try:
        try:
            _lock(handle)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            _unlock(handle)
    finally:
        handle.close()


__all__ = ["lease"]
