"""Best-effort timing records for hand-ins, separate from their decisions and manifests."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLOCKS_FILE = "hand_in_clocks.jsonl"
CLOCKS_MAX_BYTES = 2_000_000
_current: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("hand_in_clocks", default=None)
_lock = threading.Lock()
log = logging.getLogger(__name__)


def clocks_path(catalog_root: Path) -> Path:
    return Path(catalog_root) / ".thomas" / "evolve" / "agent" / CLOCKS_FILE


def _stamp(moment: float) -> str:
    return datetime.fromtimestamp(moment, timezone.utc).isoformat(timespec="milliseconds")


def _append(path: Path, record: dict[str, Any]) -> None:
    try:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line)
            if path.stat().st_size > CLOCKS_MAX_BYTES:
                lines = path.read_bytes().splitlines(keepends=True)
                kept = lines[-max(1, len(lines) // 2) :]
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=path.parent, prefix=".hand_in_clocks-", delete=False
                    ) as stream:
                        temporary = Path(stream.name)
                        stream.writelines(kept)
                    os.replace(temporary, path)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
    except Exception as exc:
        log.warning("could not write hand-in clocks to %s: %s", path, exc)


@contextmanager
def recording(catalog_root: Path, cid: str) -> Iterator[dict[str, Any]]:
    """Keep one record for this settle, writing only after its preconditions pass."""
    started = time.time()
    tick = time.monotonic()
    record: dict[str, Any] = {"conversation_id": cid, "started_at": _stamp(started), "stages": {}}
    token = _current.set(record)
    error: BaseException | None = None
    try:
        try:
            yield record
        except BaseException as exc:
            error = exc
            raise
    finally:
        try:
            ended = time.time()
            record.update(
                ended_at=_stamp(ended),
                seconds=round(time.monotonic() - tick, 3),
                outcome=type(error).__name__ if error is not None else record.get("outcome", "returned"),
            )
            if record.get("execution_id"):
                _append(clocks_path(catalog_root), record)
        finally:
            _current.reset(token)


def span(name: str, started: float, ended: float, *, seconds: float | None = None) -> None:
    """Record a stage whose work ran outside this context, such as a pool thread."""
    record = _current.get()
    if record is not None:
        elapsed = ended - started if seconds is None else seconds
        interval = {"start": _stamp(started), "end": _stamp(ended), "seconds": round(elapsed, 3)}
        with _lock:
            previous = record["stages"].get(name)
            if previous is None:
                record["stages"][name] = interval
            else:
                intervals = previous.setdefault("intervals", [dict(previous)])
                intervals.append(interval)
                previous["start"] = min(previous["start"], interval["start"])
                previous["end"] = max(previous["end"], interval["end"])
                previous["seconds"] = round(sum(item["seconds"] for item in intervals), 3)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Measure a block, including one that raises, without handling its exception."""
    record = _current.get()
    if record is None:
        yield
    else:
        started = time.time()
        tick = time.monotonic()
        try:
            yield
        finally:
            span(name, started, time.time(), seconds=time.monotonic() - tick)


def note(name: str, value: Any) -> None:
    """Attach a plain observation only when a settle is being recorded."""
    record = _current.get()
    if record is not None:
        record[name] = value


@contextmanager
def collecting() -> Iterator[dict[str, Any]]:
    """Collect a check's stages and notes without writing them: a check in its own process sends them back."""
    record: dict[str, Any] = {"stages": {}}
    token = _current.set(record)
    try:
        yield record
    finally:
        _current.reset(token)


def merge(observed: dict[str, Any]) -> None:
    """Add what :func:`collecting` gathered in a check's own process to this settle's record."""
    record = _current.get()
    if record is None or not isinstance(observed, dict):
        return
    for name, interval in (observed.get("stages") or {}).items():
        if isinstance(interval, dict):
            with _lock:
                record["stages"].setdefault(name, interval)
    for name, value in observed.items():
        if name != "stages":
            record[name] = value
