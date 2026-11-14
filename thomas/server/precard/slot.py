"""One check at a time when the parallel check is off, only with room on the disk, and nothing left behind.

With ``THOMAS_PRECARD_PARALLEL=off`` (``precard/pool.py``), :func:`one_at_a_time` holds a lock for the whole check: a
second hand-in waits for the first check to finish and then runs its own; it is never skipped. With it on, checks are
admitted side by side against the machine-wide ledger (``thomas/server/capacity_ledger.py``) instead, and this lock
is not used. Both servers need the same setting: the lock is each server's own, and a server with it off reserves
nothing in the ledger, so the other server's admissions see its checks only in the free disk they measure.

* :func:`too_little_room` refuses a serial check unless the drive has its reserve plus the check's
  estimated disk use free; parallel checks already reserve that use in the ledger. The card says why it was held.
* :func:`clear_leftovers` removes scratch copies and data folders that a check which died left behind,
  once they are older than any check can run. A check that finishes removes its own (``check._against_dev``).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from thomas.server import green_checkout
from thomas.server.capacity_ledger import disk_floor
from thomas.server.precard import scratch

log = logging.getLogger(__name__)

# Backward-compatible name for the lower bound of disk_floor's drive-sized reserve; admission also
# requires the estimated check writes, so this constant is not the complete admission threshold.
MIN_FREE_BYTES = 512 * 1024**2
_GIB = 1024**3
_lock = threading.Lock()


@contextmanager
def one_at_a_time() -> Iterator[None]:
    """Hold the only check slot for the length of the ``with`` block, waiting for it if another check has it."""
    if not _lock.acquire(blocking=False):
        log.info("the check before the card waits: another check is running")
        _lock.acquire()
    try:
        yield
    finally:
        _lock.release()


def _existing(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return path


def too_little_room(where: Path | None = None, *, disk_bytes: int = 0) -> str:
    """Why disk cannot hold estimated check writes and the drive reserve."""
    folder = _existing(Path(where) if where is not None else green_checkout.green_root())
    try:
        disk = shutil.disk_usage(folder)
        free = disk.free
        minimum = disk_floor(disk.total) + disk_bytes
    except OSError as exc:
        return f"the free space on the drive it copies to could not be read: {exc}"
    if free >= minimum:
        return ""
    return f"the check drive has {free / _GIB:.1f} GB free, and it needs at least {minimum / _GIB:g} GB"


# Named outright in tests; otherwise the system's temporary folder.
DATA_ROOT_ENV = "THOMAS_PRECARD_DATA"


def data_root() -> Path:
    """Where a check keeps its runs' data: reports, selection files and the tests' own folders.

    Never inside your real Thomas data folder. tests/conftest.py fails a session that opens anything in it, and the
    cage's greens live there (LOCALAPPDATA/Thomas/green), so with each run's reports under green_root()/precard every
    shard failed its session with all tests passed: 3603b9 and 4b24de, 2026-10-27, "pytest exit 1 contradicts its
    report" on all 16 shards.
    """
    named = str(os.environ.get(DATA_ROOT_ENV) or "").strip()
    return Path(named) if named else Path(tempfile.gettempdir()) / "thomas-precard"


def run_folder(execution_id: str) -> Path:
    """This check run's own folder under :func:`data_root`: a run removes it when it ends, so no two runs may share it.

    Named by the change alone, the tests that check one fixed execution id shared it across the shards of a real check,
    and the first to end deleted the other's selection file (d79480, 2026-10-28: "pytest exited 4", FileNotFoundError).
    """
    return data_root() / f"{execution_id}-{uuid4().hex[:8]}"


def clear_leftovers(older_than_s: float, *, now: float | None = None) -> list[str]:
    """Remove scratch copies and data folders a check that died left behind; the names it removed."""
    moment = time.time() if now is None else now
    root = green_checkout.green_root()
    removed: list[str] = []
    for git_dir in sorted((root / "git").glob(f"{scratch.PREFIX}*")) if (root / "git").is_dir() else ():
        try:
            if moment - git_dir.stat().st_mtime < older_than_s:
                continue
        except OSError:
            continue
        scratch.discard(green_checkout.find_green(git_dir.name))
        removed.append(git_dir.name)
    for data in (data_root(), root / "precard"):  # root / "precard": where checks kept their data before 2026-10-27
        for folder in sorted(data.iterdir()) if data.is_dir() else ():
            try:
                if moment - folder.stat().st_mtime < older_than_s:
                    continue
            except OSError:
                continue
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(f"precard/{folder.name}")
    if removed:
        log.warning("the check before the card cleared what an earlier check left behind: %s", ", ".join(removed))
    return removed


__all__ = [
    "DATA_ROOT_ENV",
    "MIN_FREE_BYTES",
    "clear_leftovers",
    "data_root",
    "one_at_a_time",
    "run_folder",
    "too_little_room",
]
