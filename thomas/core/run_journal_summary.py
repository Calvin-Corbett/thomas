"""The bounded summary kept beside each run's journal, readable without opening the journal.

A journal (:mod:`thomas.core.run_journal`) grows with every try of a run, while its summary stays small. The summary
holds the run id, the few labels the run was opened with (``meta``), the state of each step, the last step and its
state, whether the run was closed and how, and when it last changed. It is written after every record through a
temporary file that is flushed to the disk and then moved over the old one, so a reader sees the old summary or the new
one, never half of one. A summary that is missing, too large or unreadable reads as None. A reader then knows nothing
from it and does what it did before.

The journal uses this module directly; plugin-row integration is a later task.

Spec: docs/superpowers/specs/2026-11-04-durable-thomas-design.md section 1.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from thomas.core import atomic_json

SUMMARY_SUFFIX = ".summary.json"
MAX_SUMMARY_BYTES = 64 * 1024  # a summary is read whole, so it stays small; a larger one is refused when written
REPLACE_ATTEMPTS = 8
REPLACE_BACKOFF_S = 0.02


def summary_path(folder: Path, run_id: str) -> Path:
    return Path(folder) / f"{run_id}{SUMMARY_SUFFIX}"


def replace_with_retry(source: Path, target: Path) -> None:
    """``os.replace``, waiting out a reader that holds *target* open for a moment (Windows refuses it then)."""
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                raise
            time.sleep(REPLACE_BACKOFF_S * attempt)


def write_summary(path: Path, data: dict[str, Any]) -> None:
    """Replace the summary at *path* with *data*, synced to the disk before it takes the old one's place."""
    body = (json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    if len(body) > MAX_SUMMARY_BYTES:
        raise ValueError(f"a summary holds at most {MAX_SUMMARY_BYTES} bytes, and this one is {len(body)}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = atomic_json.temp_path_for(target)
    try:
        with open(temporary, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def read_summary(path: Path) -> dict[str, Any] | None:
    """The summary at *path*, or None when it is missing, larger than a summary can be, or does not read."""
    try:
        with open(path, "rb") as handle:
            body = handle.read(MAX_SUMMARY_BYTES + 1)
    except OSError:
        return None
    if len(body) > MAX_SUMMARY_BYTES:
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("run_id"), str) else None


def summaries(folder: Path) -> list[dict[str, Any]]:
    """Every readable summary in *folder*, by file name. No journal is opened."""
    try:
        paths = sorted(Path(folder).glob(f"*{SUMMARY_SUFFIX}"))
    except OSError:
        return []
    found = (read_summary(path) for path in paths)
    return [summary for summary in found if summary is not None]


__all__ = [
    "MAX_SUMMARY_BYTES",
    "SUMMARY_SUFFIX",
    "read_summary",
    "replace_with_retry",
    "summaries",
    "summary_path",
    "write_summary",
]
