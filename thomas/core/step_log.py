"""Every step Thomas takes, timed, in one append-only file a day, so what to improve is decided from data.

On 2026-10-25 you asked: "every single thing should be measured and tracked so we have data to pull from when we
decide what to improve". The speed board then measured five stages and left 78% of a week's time from your request to
the landing "unattributed". Each step writes one JSON line here -- a model call with its tokens, a tool call, a test
run's wait for room, a project's start, a check, a second look, a reload -- with how long it took and this PC's load
at that moment. :mod:`thomas.core.step_report` reads them back.

The file is ``<data dir>/metrics/steps-YYYYMMDD.jsonl`` (UTC day), or ``$THOMAS_STEP_LOG_DIR``; when a new day's file
starts, past days are compressed (``.jsonl.gz``) and days older than ``KEEP_DAYS`` deleted, so the record never
outgrows a small drive. Off with
``THOMAS_STEP_LOG=off``, and off under pytest unless a test sets ``THOMAS_STEP_LOG_DIR``: the suite must not write into
the real record. Never raises and never blocks on the machine reading: a step that cannot be written is dropped.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

DIR_ENV = "THOMAS_STEP_LOG_DIR"
OFF_ENV = "THOMAS_STEP_LOG"
SUBDIR = "metrics"
TEXT_CAP = 300
KEEP_DAYS = 90
_OFF = frozenset({"off", "0", "false", "no"})
_lock = threading.Lock()


def folder() -> Path | None:
    """Where the step files are, or None when the log is off."""
    if str(os.environ.get(OFF_ENV) or "").strip().lower() in _OFF:
        return None
    chosen = str(os.environ.get(DIR_ENV) or "").strip()
    if chosen:
        return Path(chosen)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return resolve_thomas_data_dir() / SUBDIR
    except (ImportError, OSError, RuntimeError, ValueError):
        return None


def day_file(base: Path, when: float) -> Path:
    return base / time.strftime("steps-%Y%m%d.jsonl", time.gmtime(when))


def prune(base: Path, now: float) -> None:
    """Compress the step files of past days (~8x smaller: ten teams write ~40 MB a day) and delete days before the
    last ``KEEP_DAYS``. A file another process still holds open is left for the next day."""
    oldest, today = day_file(base, now - KEEP_DAYS * 86400).name, day_file(base, now).name
    for path in sorted(base.glob("steps-*.jsonl*")):
        try:
            if path.name < oldest:
                path.unlink(missing_ok=True)
            elif path.suffix == ".jsonl" and path.name < today:
                packed = path.with_name(f"{path.name}.{os.getpid()}.tmp")
                with open(path, "rb") as source, gzip.open(packed, "wb") as target:
                    shutil.copyfileobj(source, target)
                os.replace(packed, path.with_name(path.name + ".gz"))
                path.unlink()
        except OSError:
            continue


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return round(value, 3)
    return str(value)[:TEXT_CAP]


def record(step: str, *, seconds: float | None = None, **fields: Any) -> None:
    """Append one step: when, which process, how long, this PC's load, and *fields*. Never raises."""
    base = folder()
    if base is None:
        return
    now = time.time()
    row: dict[str, Any] = {"ts": round(now, 3), "pid": os.getpid(), "step": str(step)[:80]}
    if seconds is not None:
        row["seconds"] = round(float(seconds), 3)
    try:
        from thomas.core import machine_load

        load = machine_load.latest()
        if load is not None:
            row["cpu"], row["memory"] = round(load.cpu, 1), round(load.memory, 1)
    except (ImportError, OSError, RuntimeError, ValueError):
        pass
    row.update({str(key)[:60]: _plain(value) for key, value in fields.items() if value is not None})
    try:
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _lock:
            base.mkdir(parents=True, exist_ok=True)
            path = day_file(base, now)
            if not path.exists():  # a new day: past days are packed off this thread, so no step waits for it
                threading.Thread(target=prune, args=(base, now), name="step-log-prune", daemon=True).start()
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
    except (OSError, TypeError, ValueError):
        return


def tool_finished(event: Any, *, run: str = "") -> Any:
    """Record a finished tool call from its result event (``duration_ms``, ``tool_name``, ``ok``); returns the event."""
    data = getattr(event, "data", None)
    if isinstance(data, dict) and isinstance(data.get("duration_ms"), (int, float)):
        timed_out = "timed out" in str(data.get("result_text") or "")[:80]
        outcome = "timeout" if timed_out else ("ok" if data.get("ok", True) else "failed")
        record("tool", seconds=data["duration_ms"] / 1000, run=run, tool=data.get("tool_name"), outcome=outcome)
    return event


class _Timed:
    def __init__(self, step: str, fields: dict[str, Any]) -> None:
        self.step, self.fields, self.extra = step, fields, {}
        self.started = 0.0

    def __enter__(self) -> dict[str, Any]:
        self.started = time.monotonic()
        return self.extra

    def __exit__(self, kind: type[BaseException] | None, _value: object, _tb: object) -> None:
        if kind is not None:  # seen, never caught: returning None lets it go on
            self.extra.setdefault("outcome", f"raised {kind.__name__}")
        record(self.step, seconds=time.monotonic() - self.started, **self.fields, **self.extra)


def timed(step: str, **fields: Any) -> _Timed:
    """Time the block and record it; the block may add fields (an outcome) to the dict it gets. An exception is
    recorded as the outcome and goes on."""
    return _Timed(step, fields)


def read(days: float = 1.0, *, base: Path | None = None, now: float | None = None) -> list[dict[str, Any]]:
    """Every step of the last *days* days, oldest first. A line that is not JSON is skipped."""
    base = base if base is not None else folder()
    if base is None:
        return []
    now = time.time() if now is None else now
    since = now - days * 86400
    rows: list[dict[str, Any]] = []
    day = since
    seen: set[Path] = set()
    while day <= now + 86400:
        path = day_file(base, day)
        day += 86400
        packed = path.with_name(path.name + ".gz")
        if path in seen or not (path.is_file() or packed.is_file()):
            continue
        seen.add(path)
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                text = gzip.decompress(packed.read_bytes()).decode("utf-8", errors="replace")
        except (OSError, EOFError):
            continue
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and float(row.get("ts") or 0) >= since:
                rows.append(row)
    rows.sort(key=lambda row: float(row.get("ts") or 0))
    return rows


__all__ = ["DIR_ENV", "KEEP_DAYS", "OFF_ENV", "day_file", "folder", "prune", "read", "record", "timed"]
