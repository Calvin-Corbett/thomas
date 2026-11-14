"""Retention and compaction for run journals.

Closed runs are retained for a week; stale open runs are first marked abandoned.
Compaction streams the journal and keeps the latest record for each distinct step,
so its memory use scales with those records rather than the journal's history.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

from thomas.core import atomic_json, run_journal, run_journal_summary

log = logging.getLogger(__name__)
KEEP_CLOSED_S = 7 * 86400.0
ABANDON_AFTER_S = 30 * 86400.0
COMPACT_BYTES = 256 * 1024

# The quarantine writer uses a numeric time_ns stamp. Requiring the complete
# filename avoids treating unrelated files containing '.damaged-' as backups.
_DAMAGED_NAME = re.compile(r"([A-Za-z0-9][A-Za-z0-9_-]{0,127})\.journal\.damaged-[0-9]+")
_VALID_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def compact(path: Path, run_id: str) -> int:
    """Atomically retain the latest record per step and return the new byte size.

    Replay reads incrementally; memory is proportional to the latest records of
    distinct steps. Journal opens and writes wait until replacement finishes.
    A source deleted before the lock is acquired raises FileNotFoundError without
    creating a replacement, so an expired owner's missing-history guard stays valid.
    """
    path = Path(path)
    with run_journal._run_lock(path):
        return _compact_locked(path, run_id)


def _compact_locked(path: Path, run_id: str) -> int:
    # Replay treats a missing journal as a fresh run; maintenance must not recreate it.
    path.stat()
    state = run_journal.replay(path, run_id)
    temporary = atomic_json.temp_path_for(path)
    size = 0
    try:
        with open(temporary, "wb") as handle:
            for step in sorted(state.latest):
                line = state.latest[step].line()
                handle.write(line)
                size += len(line)
            handle.flush()
            os.fsync(handle.fileno())
        run_journal_summary.replace_with_retry(temporary, path)
        try:
            run_journal._sync_directory(path.parent)
        except OSError:
            # Existing owners must replay and sync entries before acknowledging more work.
            run_journal._run_generations[run_journal._run_lock(path)] = object()
            raise
    finally:
        temporary.unlink(missing_ok=True)
    return size


def sweep(
    folder: Path,
    *,
    now: float | None = None,
    keep_closed_s: float = KEEP_CLOSED_S,
    abandon_after_s: float = ABANDON_AFTER_S,
    compact_bytes: int = COMPACT_BYTES,
) -> dict[str, list[str]]:
    """Apply retention to a folder, isolating failures to individual files."""
    moment = time.time() if now is None else float(now)
    done: dict[str, list[str]] = {"removed": [], "abandoned": [], "compacted": [], "damaged_removed": []}
    try:
        paths = sorted(Path(folder).iterdir())
    except OSError:
        return done
    for path in paths:
        try:
            _sweep_one(path, moment, done, keep_closed_s, abandon_after_s, compact_bytes)
        except (OSError, ValueError) as exc:
            # JournalDamaged is an OSError: one damaged run must not stop others.
            log.warning("journal file %s could not be swept: %s", path.name, exc)
    return done


def _sweep_one(
    path: Path,
    now: float,
    done: dict[str, list[str]],
    keep_closed_s: float,
    abandon_after_s: float,
    compact_bytes: int,
) -> None:
    name = path.name
    damaged = _DAMAGED_NAME.fullmatch(name)
    if damaged:
        source = path.with_name(f"{damaged.group(1)}{run_journal.JOURNAL_SUFFIX}")
        with run_journal._run_lock(source):
            if now - path.stat().st_mtime > keep_closed_s:
                path.unlink(missing_ok=True)
                done["damaged_removed"].append(name)
        return
    if not name.endswith(run_journal_summary.SUMMARY_SUFFIX):
        return
    summary = run_journal_summary.read_summary(path)
    if summary is None:
        return
    run_id = summary["run_id"]
    if not _VALID_RUN_ID.fullmatch(run_id):
        return
    run_journal.check_run_id(run_id)
    if path != run_journal_summary.summary_path(path.parent, run_id):
        return
    lock = run_journal._run_lock(path.with_name(f"{run_id}{run_journal.JOURNAL_SUFFIX}"))
    with lock:
        if run_journal._active_executions.get(lock, 0):
            return
        _retain_locked(path, run_id, now, done, keep_closed_s, abandon_after_s, compact_bytes)


def _retain_locked(
    path: Path,
    run_id: str,
    now: float,
    done: dict[str, list[str]],
    keep_closed_s: float,
    abandon_after_s: float,
    compact_bytes: int,
) -> None:
    summary = run_journal_summary.read_summary(path)
    if summary is None or summary["run_id"] != run_id:
        return
    closed = summary.get("closed", "")
    if not isinstance(closed, str):
        return
    journal = path.with_name(f"{run_id}{run_journal.JOURNAL_SUFFIX}")
    age = now - path.stat().st_mtime
    if not closed:
        if age > abandon_after_s:
            updated = {**summary, "closed": "abandoned", "updated_at": run_journal.utc_now()}
            run_journal_summary.write_summary(path, updated)
            done["abandoned"].append(run_id)
        return
    if age > keep_closed_s:
        journal.unlink(missing_ok=True)
        run_journal._run_generations[run_journal._run_lock(journal)] = object()
        path.unlink(missing_ok=True)
        done["removed"].append(run_id)
    elif journal.is_file() and journal.stat().st_size > compact_bytes:
        compact(journal, run_id)
        done["compacted"].append(run_id)


__all__ = ["ABANDON_AFTER_S", "COMPACT_BYTES", "KEEP_CLOSED_S", "compact", "sweep"]
