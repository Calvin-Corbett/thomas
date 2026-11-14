"""Size-triggered board archiving for a process that already runs periodically. stdlib only.

``archive_if_large`` is the call the worker idle loop makes (scripts/crew/workboard/worker.py via
worker_dispatch.py). Under the threshold it is one ``stat``: no lock, no read. Over it, it takes the
board lock and archives exactly as ``archive_board_messages.py --apply`` does, by import, not by
spawning a process.

Failures are logged here and then raised; the caller decides what to do with them. A held lock is the
one expected contention (several workers can notice the same big board): it is logged and reported as
``skipped`` because the next idle tick retries. So is a running git commit or stash (``.git/index.lock``).

A run that finds nothing movable is remembered by the board's size and mtime (a small file beside the
board lock). Until the board changes, no worker locks, reads or parses it again: an unshrinkable board
must not cost every idle worker a locked parse every five minutes.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts.praxis import archive_board_messages as cli
from scripts.praxis import archive_io

logger = logging.getLogger(__name__)

DEFAULT_MIN_BOARD_BYTES = 256 * 1024
LOCK_TIMEOUT_SECONDS = 2.0
# One run never moves more than this, so its uncommitted diff (rows removed here, rows added to the
# archive) stays well under the 800 changed-line worktree budget; the next idle tick takes the rest.
MAX_ROWS_PER_RUN = 300
NOOP_FILE = "board_archive_noop.json"


def _stamp(board: Path) -> dict[str, int]:
    info = board.stat()
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns}


def _remembered_noop(path: Path, board: Path) -> bool:
    """True when the last run found nothing to move and the board has not changed since."""
    try:
        return json.loads(path.read_text(encoding="utf-8")) == _stamp(board)
    except (OSError, ValueError):
        return False


def _remember_noop(path: Path, board: Path) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(_stamp(board)), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.warning("board archive could not record its no-op result in %s; the next tick re-checks", path)
        tmp.unlink(missing_ok=True)


def _run(board: Path, root: Path, noop_file: Path, **settings) -> dict[str, object]:
    result = cli.apply_archive(board, board.parent / "archive", root=root, **settings)
    if not result["rows_moved"]:
        _remember_noop(noop_file, board)
    return result


def archive_if_large(
    board: Path,
    *,
    root: Path,
    min_bytes: int = DEFAULT_MIN_BOARD_BYTES,
    now: datetime | None = None,
    keep_days: float = cli.DEFAULT_KEEP_DAYS,
    stale_open_days: float = cli.DEFAULT_STALE_OPEN_DAYS,
    lock_timeout: float = LOCK_TIMEOUT_SECONDS,
    max_rows: int = MAX_ROWS_PER_RUN,
) -> dict[str, object] | None:
    """None while the board is under ``min_bytes``; otherwise the result of one archive run."""
    if min_bytes <= 0 or board.stat().st_size < min_bytes:
        return None
    coordination = archive_io.canonical_root(root) / "runtime" / "coordination"
    noop_file = coordination / NOOP_FILE
    if _remembered_noop(noop_file, board):
        return {"noop": "nothing movable and the board has not changed since the last run"}
    reason = archive_io.busy_reason(root)
    if reason:
        logger.warning("board archive skipped, will retry on the next idle tick: %s", reason)
        return {"skipped": reason}
    try:
        return cli.locked(
            coordination,
            coordination / "workboard.lock",
            lock_timeout,
            _run,
            board,
            root,
            noop_file,
            now=now or datetime.now(timezone.utc),
            keep_days=keep_days,
            stale_open_days=stale_open_days,
            max_rows=max_rows,
        )
    except archive_io.Busy as exc:
        logger.warning("board archive skipped, will retry on the next idle tick: %s", exc)
        return {"skipped": str(exc)}
    except (OSError, RuntimeError, ValueError):
        logger.exception("board archive failed; the board was not swapped in")
        raise
