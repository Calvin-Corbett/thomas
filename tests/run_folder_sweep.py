"""Remove the data folders earlier test runs left behind in the temp folder.

Every pytest session makes a ``thomas-test-data-*`` folder (conftest.py) and removes it when it ends, ignoring errors.
A shard stopped for time never reaches that, and a file another program holds open (Defender, Windows Search, a
SQLite handle) makes the removal give up silently: on 2026-11-06 one account's temp folder held 1,992 of them, and
Windows Search spent about a core indexing test folders. Each session that ends now also removes a few folders left
by sessions long over; a run never lasts six hours, so a folder that old belongs to no live run.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

PREFIX = "thomas-test-data-"
MAX_AGE_S = 6 * 3600
LIMIT = 40  # per session, so a session's end never waits long; ~16 sessions a check drain a backlog quickly


def sweep(
    parent: Path, *, own: Path, now: float | None = None, max_age_s: float = MAX_AGE_S, limit: int = LIMIT
) -> int:
    """Remove up to *limit* ``thomas-test-data-*`` folders in *parent* older than *max_age_s*, never *own*."""
    now = time.time() if now is None else now
    removed = 0
    try:
        found = sorted(parent.glob(PREFIX + "*"))
    except OSError:
        return 0
    for folder in found:
        if removed >= limit:
            break
        try:
            if folder == own or folder.is_symlink() or not folder.is_dir():
                continue
            if now - folder.stat().st_mtime < max_age_s:
                continue
        except OSError:
            continue
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            removed += 1
    return removed
