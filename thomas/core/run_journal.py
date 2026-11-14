"""Each run's journal: an append-only record of its steps on the disk, read back to resume the run where it stopped.

A run (a build, a check, a hand-in) writes one record when a step starts, holding the step's input, and one when it
finishes, holding its result. Each record is one line of JSON, flushed and synced to the disk before the call returns,
so the next step never begins before the last one is written down. Reading a journal back (:func:`replay`) goes one
line at a time and keeps only the latest record of each step, so a journal of any length is never held whole.

What a run does with what it reads back (:meth:`Journal.resume`, :meth:`Journal.run_step`):

- A finished step is not done again. Its saved result is used.
- A step that was cut off halfway is done again from its saved input.
- A cut-off step that changes something outside the journal (the caller names those steps in ``effects``) is marked
  ``unknown``. It is not done again until the run has checked what it did (:class:`StepUnknown`).

A last line that a crash cut off partway is not damage. It is the record of a step that never reached the disk whole,
and it is cut away before the next write. Any other line that does not read is damage
(:class:`~thomas.core.journal_lent.JournalDamaged`). Failing to open or read the file is not
damage: that is an ``OSError``, and the next try reads it again.

Records hold exactly the fields the spec names: run id, step number, step state, step input, step result, started and
finished times in ISO-8601 UTC. The summary beside each journal is :mod:`thomas.core.run_journal_summary`.
The plugin row and hand-in integration are deferred to later tasks in the plan.
Only one instance/process may own a run. Overlapping ``run_step`` calls on that instance are rejected before work.
POSIX directory entries are synced before work; Windows syncs file contents but skips directory fsync, which its
CRT does not support. Power-loss durability of new Windows pathnames is not guaranteed here.

Spec: docs/superpowers/specs/2026-11-04-durable-thomas-design.md section 1.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core import run_journal_summary
from thomas.core.journal_lent import JournalDamaged

STARTED, FINISHED, UNKNOWN = "started", "finished", "unknown"
STATES = frozenset({STARTED, FINISHED, UNKNOWN})
FIELDS = ("run_id", "step", "state", "input", "result", "started_at", "finished_at")
MAX_RECORD_BYTES = 1024 * 1024  # one record is one line; a longer line is damage, and is never read whole
JOURNAL_SUFFIX = ".journal"
DAMAGED_MARK = ".damaged-"
log = logging.getLogger(__name__)
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")  # no dot and no slash: a run id never leaves its folder


def utc_now() -> str:
    """Now, in ISO-8601 UTC to the millisecond, such as ``2026-11-04T09:15:02.123Z``."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def check_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
        raise ValueError(f"not a run id: {run_id!r}")
    return run_id


def _step(step: int) -> int:
    if not isinstance(step, int) or isinstance(step, bool) or step < 1:
        raise ValueError(f"a step number is a whole number from 1: {step!r}")
    return step


@dataclass(frozen=True)
class Record:
    """One line of a journal."""

    run_id: str
    step: int
    state: str
    input: Any = None
    result: Any = None
    started_at: str = ""
    finished_at: str = ""

    def line(self) -> bytes:
        data = {name: getattr(self, name) for name in FIELDS}
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError(f"step {self.step} of {self.run_id} is {len(raw)} bytes, over {MAX_RECORD_BYTES}")
        return raw

    @classmethod
    def parse(cls, raw: bytes, run_id: str) -> Record:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or set(data) != set(FIELDS):
            raise ValueError("a record holds exactly the journal's fields")
        if data["run_id"] != run_id or data["state"] not in STATES:
            raise ValueError("a record of another run, or in no known state")
        _step(data["step"])
        return cls(**data)


@dataclass
class Replay:
    """What a journal says: the latest record of each step, and where its last whole line ends."""

    run_id: str
    latest: dict[int, Record] = field(default_factory=dict)
    end: int = 0
    torn: bool = False  # the last line was cut off by a crash mid-write and is not counted

    def _in(self, state: str) -> dict[int, Record]:
        return {step: record for step, record in sorted(self.latest.items()) if record.state == state}

    @property
    def finished(self) -> dict[int, Record]:
        return self._in(FINISHED)

    @property
    def cut_off(self) -> dict[int, Record]:
        return self._in(STARTED)

    @property
    def unknown(self) -> dict[int, Record]:
        return self._in(UNKNOWN)

    @property
    def last_finished(self) -> int:
        return max(self.finished, default=0)


def replay(path: Path, run_id: str) -> Replay:
    """Read the journal at *path* one line at a time. An empty Replay when there is none yet.

    Raises :class:`JournalDamaged` for a line that does not read, other than a last line a crash cut off, and an
    ``OSError`` when the file is there but cannot be opened or read just now.
    """
    found = Replay(check_run_id(run_id))
    try:
        handle = open(path, "rb")
    except FileNotFoundError:
        return found
    with handle:
        number = 0
        while True:
            raw = handle.readline(MAX_RECORD_BYTES + 1)
            if not raw:
                return found
            number += 1
            if len(raw) > MAX_RECORD_BYTES:
                raise JournalDamaged(f"line {number} is longer than a record can be")
            if not raw.endswith(b"\n"):
                found.torn = True  # the last write, cut off by a crash: that step never reached the disk whole
                return found
            try:
                record = Record.parse(raw, run_id)
            except (ValueError, TypeError, RecursionError) as exc:
                raise JournalDamaged(f"line {number} could not be read ({type(exc).__name__})") from exc
            found.latest[record.step] = record
            found.end += len(raw)


@dataclass(frozen=True)
class Resume:
    """Where a run picks up. ``finished`` steps are not done again. ``redo`` steps are done again from their saved
    input. ``unknown`` steps are checked before they are done again."""

    finished: dict[int, Record]
    redo: dict[int, Record]
    unknown: dict[int, Record]


class StepUnknown(RuntimeError):
    """A step was cut off after it may have changed something: its result is unknown, so check it before redoing it."""

    def __init__(self, record: Record) -> None:
        super().__init__(f"step {record.step} of {record.run_id} was cut off and its result is unknown")
        self.record = record


def _same(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if key != "updated_at"}


def _cut_to(path: Path, end: int) -> None:
    """Cut away a last line a crash left half-written, so the next record starts on a line of its own."""
    with open(path, "r+b") as handle:
        handle.truncate(end)
        handle.flush()
        os.fsync(handle.fileno())


def _sync_directory(path: Path) -> None:
    """Persist directory entries on POSIX; Windows has no portable directory-fsync API.

    On Windows file contents are synced, but pathname survival across power loss is not guaranteed.
    """
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


_run_locks: weakref.WeakValueDictionary[str, Any] = weakref.WeakValueDictionary()
_run_locks_guard = threading.Lock()
_run_generations: weakref.WeakKeyDictionary[Any, object] = weakref.WeakKeyDictionary()
_active_executions: dict[Any, int] = {}  # accessed under the corresponding per-run lock


def _run_lock(path: Path) -> Any:
    """Share maintenance exclusion across owners and facades in this process."""
    key = os.path.normcase(str(Path(path).resolve()))
    with _run_locks_guard:
        lock = _run_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _run_locks[key] = lock
        return lock


class Journal:
    """One run's journal and its summary, in *folder*. ``meta`` labels the run in its summary. Left out, the labels
    the summary already has are kept. Use one Journal instance per run and one process to execute it;
    overlapping run_step calls on that instance are rejected before invoking work."""

    def __init__(self, folder: Path, run_id: str, *, meta: dict[str, Any] | None = None) -> None:
        self.run_id = check_run_id(run_id)
        self.folder = Path(folder)
        self.path = self.folder / f"{run_id}{JOURNAL_SUFFIX}"
        self.summary_path = run_journal_summary.summary_path(self.folder, run_id)
        self._lock = _run_lock(self.path)
        self._execution = threading.Lock()
        self._entries_synced = False
        self._append_failed = False
        with self._lock:
            self._generation = _run_generations.setdefault(self._lock, object())
            self._state = replay(self.path, run_id)
            if self._state.torn:
                _cut_to(self.path, self._state.end)
                self._state.torn = False
            before = run_journal_summary.read_summary(self.summary_path) or {}
            self.meta: dict[str, Any] = dict(meta) if meta is not None else dict(before.get("meta") or {})
            self.closed: str = str(before.get("closed") or "")
            # Repair a summary left behind by a crash after a record was persisted.
            if (self._state.latest or meta is not None) and _same(before) != _same(self.summary()):
                run_journal_summary.write_summary(self.summary_path, self.summary())

    @property
    def state(self) -> Replay:
        return self._state

    def summary(self) -> dict[str, Any]:
        latest = self._state.latest
        last = max(latest, default=0)
        return {
            "run_id": self.run_id,
            "meta": self.meta,
            "steps": {str(step): record.state for step, record in sorted(latest.items())},
            "last_step": last,
            "last_state": latest[last].state if last else "",
            "closed": self.closed,
            "updated_at": utc_now(),
        }

    def _require_writable(self) -> None:
        if self._append_failed:
            raise OSError("journal append failed; reopen the journal before continuing")
        if _run_generations.get(self._lock) is not self._generation or (self._state.latest and not self.path.exists()):
            raise OSError("journal history was removed; reopen the journal before continuing")

    def _sync_entries(self) -> None:
        if self._entries_synced:
            return
        # Include ancestors created by a previous attempt or by a summary write.
        folder = self.folder.resolve()
        try:
            for directory in (folder, *folder.parents):
                _sync_directory(directory)
        except OSError:
            self._append_failed = True
            raise
        self._entries_synced = True

    def _append(self, record: Record) -> Record:
        raw = record.line()
        record = Record.parse(raw, self.run_id)
        with self._lock:
            self._require_writable()
            published = False
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                with open(self.path, "ab") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())  # on the disk before the next step can begin
                self._sync_entries()
                self._state.latest[record.step] = record
                self._state.end += len(raw)
                published = True
            finally:
                # Any exit before publication, including cancellation, needs replay to decide what survived.
                if not published:
                    self._append_failed = True
            run_journal_summary.write_summary(self.summary_path, self.summary())
        return record

    def start(self, step: int, step_input: Any = None) -> Record:
        return self._append(Record(self.run_id, _step(step), STARTED, step_input, None, utc_now(), ""))

    def finish(self, step: int, result: Any = None) -> Record:
        begun = self._state.latest.get(_step(step))
        if begun is None or begun.state != STARTED:
            raise ValueError(f"step {step} of {self.run_id} is not running, so it cannot finish")
        return self._append(Record(self.run_id, step, FINISHED, begun.input, result, begun.started_at, utc_now()))

    def mark_unknown(self, step: int) -> Record:
        begun = self._state.latest.get(_step(step))
        if begun is None or begun.state != STARTED:
            raise ValueError(f"step {step} of {self.run_id} was not cut off, so its result is not unknown")
        return self._append(Record(self.run_id, step, UNKNOWN, begun.input, None, begun.started_at, ""))

    def resume(self, *, effects: Iterable[int] = ()) -> Resume:
        """Mark each cut-off step named in *effects* unknown, then say where the run picks up."""
        marked = {_step(step) for step in effects}
        for step in self._state.cut_off:
            if step in marked:
                self.mark_unknown(step)
        return Resume(self._state.finished, self._state.cut_off, self._state.unknown)

    def run_step(self, step: int, step_input: Any, work: Callable[[Any], Any]) -> Any:
        """The step's saved result when it finished before. Otherwise *work* runs on its input (a cut-off step's saved
        input) and the step finishes. Raises :class:`StepUnknown` for a step whose result is unknown."""
        if not self._execution.acquire(blocking=False):
            raise RuntimeError("this journal is already executing a step")
        pinned = False
        try:
            with self._lock:
                self._require_writable()
                _active_executions[self._lock] = _active_executions.get(self._lock, 0) + 1
                pinned = True
            record = self._state.latest.get(_step(step))
            if record is not None and record.state == FINISHED:
                return json.loads(json.dumps(record.result))
            if record is not None and record.state == UNKNOWN:
                raise StepUnknown(record)
            if record is not None and record.state == STARTED:
                # A reopened record may be from an append whose directory sync failed.
                if not self._entries_synced:
                    try:
                        with open(self.path, "r+b") as handle:
                            os.fsync(handle.fileno())
                        self._sync_entries()
                    except OSError:
                        self._append_failed = True
                        raise
                step_input = record.input  # cut off halfway: done again from the input it was saved with
            else:
                step_input = self.start(step, step_input).input
            result = work(json.loads(json.dumps(step_input)))
            self.finish(step, result)
            return result
        finally:
            with self._lock:
                if pinned:
                    remaining = _active_executions[self._lock] - 1
                    if remaining:
                        _active_executions[self._lock] = remaining
                    else:
                        del _active_executions[self._lock]
            self._execution.release()

    def close(self, outcome: str) -> None:
        """Store how the run ended in its summary, without adding a journal record."""
        with self._lock:
            self._require_writable()
            self.closed = str(outcome or "closed")[:80]
            run_journal_summary.write_summary(self.summary_path, self.summary())


class RunJournals:
    """Folder-scoped journals; damage quarantines and stops only the affected run.

    The optional reporter records the problem for the caller. A broken reporter
    cannot turn journal damage into a failure of unrelated runs.
    """

    def __init__(self, *, on_damage: Callable[[str, str], None] | None = None) -> None:
        self._on_damage = on_damage
        self._folders: set[Path] = set()
        self._lock = threading.Lock()

    def _remember(self, folder: Path) -> Path:
        place = Path(folder)
        with self._lock:
            self._folders.add(place)
        return place

    def open(self, folder: Path, run_id: str, *, meta: dict[str, Any] | None = None) -> Journal:
        check_run_id(run_id)
        place = self._remember(folder)
        with _run_lock(place / f"{run_id}{JOURNAL_SUFFIX}"):
            return self._open_locked(place, run_id, meta=meta)

    def _open_locked(self, place: Path, run_id: str, *, meta: dict[str, Any] | None) -> Journal:
        try:
            return Journal(place, run_id, meta=meta)
        except JournalDamaged as exc:
            # Detection revokes owners under the run lock even when quarantine fails.
            _run_generations[_run_lock(place / f"{run_id}{JOURNAL_SUFFIX}")] = object()
            why = f"{exc}; {_set_aside(place, run_id)}"
            if self._on_damage is not None:
                try:
                    self._on_damage(run_id, why)
                except Exception:
                    log.exception("the damage to the journal of run %s could not be recorded", run_id)
            raise JournalDamaged(why) from exc

    def summary(self, folder: Path, run_id: str) -> dict[str, Any] | None:
        check_run_id(run_id)
        return run_journal_summary.read_summary(run_journal_summary.summary_path(self._remember(folder), run_id))

    def summaries(self, folder: Path) -> list[dict[str, Any]]:
        return run_journal_summary.summaries(self._remember(folder))

    def folders(self) -> list[Path]:
        with self._lock:
            return sorted(self._folders)

    def sweep(self, *, now: float | None = None) -> dict[str, dict[str, list[str]]]:
        from thomas.core import run_journal_retention

        return {str(place): run_journal_retention.sweep(place, now=now) for place in self.folders()}


def _set_aside(folder: Path, run_id: str) -> str:
    """Keep the damaged bytes for a week, or leave the original if renaming fails."""
    journal = folder / f"{run_id}{JOURNAL_SUFFIX}"
    aside = journal.with_name(f"{journal.name}{DAMAGED_MARK}{time.time_ns()}")
    moved = False
    try:
        os.replace(journal, aside)
        moved = True
        os.utime(aside, None)
        run_journal_summary.summary_path(folder, run_id).unlink(missing_ok=True)
    except OSError as exc:
        if moved:
            try:
                os.replace(aside, journal)
            except OSError:
                log.exception("the damaged journal of run %s could not be restored", run_id)
        return f"it could not be set aside ({type(exc).__name__})"
    return f"kept as {aside.name}"


__all__ = [
    "DAMAGED_MARK",
    "FIELDS",
    "FINISHED",
    "JOURNAL_SUFFIX",
    "MAX_RECORD_BYTES",
    "STARTED",
    "UNKNOWN",
    "Journal",
    "JournalDamaged",
    "Record",
    "Replay",
    "Resume",
    "RunJournals",
    "StepUnknown",
    "check_run_id",
    "replay",
    "utc_now",
]
