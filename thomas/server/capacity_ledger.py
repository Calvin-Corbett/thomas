"""One reservation ledger for every server on this machine (spec 2026-10-12 Part 1 item 5).

In this release checks are admitted here (kind ``check``, disk only: :mod:`thomas.server.precard.check`), their pytest
shards reserve from it, and second looks take their turns in it (kind ``second_look``, no disk or memory:
:mod:`thomas.server.precard.review_dial`); train checks and Build launches come later. The caged server and your own
server both read and write it. A job starts only when, after its own reservation, measured free disk stays at or above
a drive-sized disk reserve
(:data:`FLOOR_BYTES`) and memory stays inside what the machine has after its reserve. Jobs of one kind wait in one
line: fewest files first, one place gained per minute waited, and anything waiting 15 minutes goes next
(:func:`order`). Two jobs with one id never run at once. Each server process also records its own P here, and every
shard uses the smallest (:func:`pool_size`).

The ledger is ``reservations.json`` beside ``hand_in_holds.json`` in the catalog's ``.thomas/evolve/agent``, the one
folder both servers share, read and written under the locks of :mod:`~thomas.server.capacity_ledger_locks`; a write
goes through a temporary file of its own, flushed to the disk first (:mod:`~thomas.server.capacity_ledger_file`). A row
whose owner process has died is dropped, and so is a row of this process that no job of it holds any more (its release
could not be written). A file that cannot be read is never taken for an empty ledger. Memory is counted against total
memory less the reserve, and against measured free memory only for :data:`WARM_S` seconds after admission: a job running
longer already uses its memory, which "available" no longer includes.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.core import machine_capacity
from thomas.server import capacity_ledger_file
from thomas.server import capacity_ledger_locks as locks

log = logging.getLogger(__name__)

FLOOR_BYTES = 2 * 1024**3  # maximum reserve; smaller drives keep 5% (at least 512 MiB)
ROOT_ENV = "THOMAS_CAPACITY_LEDGER_ROOT"
NAME = "reservations.json"
POLL_S = 1.0
GOES_NEXT_S = 900.0
WARM_S = 60.0
POOL_KIND = "pool_size"
_GIB = 1024**3
_changed = threading.Condition()


class NotAdmitted(RuntimeError):
    """No room for a job: waiting cannot help (``waited`` is False), or it waited as long as it may (True)."""

    def __init__(self, why: str, *, waited: bool) -> None:
        super().__init__(why)
        self.waited = waited


@dataclass(frozen=True)
class Room:
    """What was measured just before an admission: free disk on the job's drive, total and available memory."""

    free_disk: int
    total_ram: int | None
    available_ram: int | None
    total_disk: int | None = None


def folder() -> Path:
    """Where the ledger lives: :data:`ROOT_ENV`, else the catalog's ``.thomas/evolve/agent``."""
    named = str(os.environ.get(ROOT_ENV) or "").strip()
    if named:
        return Path(named)
    return _catalog_root() / ".thomas" / "evolve" / "agent"


def _catalog_root() -> Path:
    """The catalog ``thomas_project._catalog_root`` names, without importing it.

    Importing thomas_project reached 935 files, nearly all of thomas/server (2026-10-29), so every check's proof needed
    the whole server. Loaded, its resolver is asked (a test may have redirected it); not loaded, nothing has, and its
    resolver returns the checkout this file is in.
    """
    project = sys.modules.get("thomas.server.thomas_project")
    return Path(project._catalog_root()) if project is not None else Path(__file__).resolve().parents[2]


def measure(where: Path) -> Room:
    """Free disk on *where*'s drive (its nearest folder that exists), and total and available memory."""
    folder_now = next((path for path in (Path(where), *Path(where).parents) if path.exists()), Path(where))
    total, available = machine_capacity._memory()
    disk = shutil.disk_usage(folder_now)
    return Room(int(disk.free), total, available, int(disk.total))


def disk_floor(total_disk: int | None) -> int:
    """Reserve 5% of the drive, bounded between 512 MiB and 2 GiB."""
    if total_disk is None:
        return FLOOR_BYTES  # callers without drive capacity keep a conservative reserve
    return min(FLOOR_BYTES, max(512 * 1024**2, total_disk // 20))


def _drive(where: Path) -> str:
    return os.path.splitdrive(os.path.abspath(str(where)))[0].lower() or "/"


def _short_disk(rows: list[dict[str, Any]], disk_bytes: int, drive: str, room: Room) -> str:
    """Why *disk_bytes* more on *drive* would leave less than the floor beside the admitted rows; "" when it fits."""
    held = sum(
        int(row.get("disk_bytes") or 0) for row in rows if row.get("state") == "admitted" and row.get("drive") == drive
    )
    floor = disk_floor(room.total_disk)
    if disk_bytes > 0 and room.free_disk - held - disk_bytes < floor:
        return (
            f"the drive has {room.free_disk / _GIB:.1f} GB free and {held / _GIB:.1f} GB of it is promised to "
            f"running jobs, so {disk_bytes / _GIB:.1f} GB more would leave less than {floor / _GIB:g} GB"
        )
    return ""


def _short_memory(rows: list[dict[str, Any]], memory_bytes: int, room: Room, now: float) -> str:
    """Why *memory_bytes* more does not fit beside the admitted rows; "" when it does."""
    if memory_bytes <= 0:
        return ""
    admitted = [row for row in rows if row.get("state") == "admitted"]
    held = sum(int(row.get("memory_bytes") or 0) for row in admitted)
    ceiling = machine_capacity.usable_memory_bytes(room.total_ram, None)
    if room.total_ram is not None and ceiling is not None and held + memory_bytes > ceiling:
        return (
            f"running jobs hold {held / _GIB:.1f} GB of the {ceiling / _GIB:.1f} GB of memory this machine leaves "
            f"after its reserve, and this one needs {memory_bytes / _GIB:.1f} GB"
        )
    if room.available_ram is not None:
        fresh = sum(
            int(row.get("memory_bytes") or 0) for row in admitted if now - float(row.get("admitted_at") or 0.0) < WARM_S
        )
        if room.available_ram - fresh - memory_bytes < 0:
            return f"{room.available_ram / _GIB:.1f} GB of memory is free and jobs just started will use it"
    return ""


def refusal(
    rows: list[dict[str, Any]], *, disk_bytes: int, memory_bytes: int, drive: str, room: Room, now: float
) -> str:
    """Why a job reserving *disk_bytes* and *memory_bytes* does not fit beside the admitted rows; "" when it does."""
    return _short_disk(rows, disk_bytes, drive, room) or _short_memory(rows, memory_bytes, room, now)


def order(rows: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    """The waiting rows in the order they go: 15 minutes waited goes next, then fewest files less minutes waited."""
    waiting = [row for row in rows if row.get("state") == "waiting"]

    def since(row: dict[str, Any]) -> float:
        value = row.get("since")
        return now if value is None else float(value)

    def waited(row: dict[str, Any]) -> float:
        return max(0.0, now - since(row))

    overdue = sorted((row for row in waiting if waited(row) >= GOES_NEXT_S), key=since)
    rest = sorted(
        (row for row in waiting if waited(row) < GOES_NEXT_S),
        key=lambda row: (int(row.get("files") or 0) - waited(row) / 60.0, since(row)),  # a tie: the order written
    )
    return overdue + rest


def _read(place: Path) -> list[dict[str, Any]]:
    return locks.read_rows(place, NAME)  # raises rather than return [] for a file it could not read


def _write(place: Path, rows: list[dict[str, Any]]) -> None:
    capacity_ledger_file.write(place, NAME, rows)  # flushed to the disk, then renamed over the file


def _live(place: Path) -> tuple[list[dict[str, Any]], bool]:
    """The ledger's live rows (:func:`capacity_ledger_locks.alive`), and whether any were dropped."""
    return locks.alive(place, _read(place), standing=POOL_KIND)


def pool_size(own: int, *, root: Path | None = None) -> int:
    """P for every shard on this machine: the smallest P any live server process computed, *own* among them.

    Each process keeps its own P as a row of kind :data:`POOL_KIND`, dropped with the rest when its owner dies.
    """
    place = Path(root) if root is not None else folder()
    mine = max(1, int(own))
    with locks.locked(place, NAME):
        current, dropped = _live(place)
        key = f"{POOL_KIND}:{locks.owner(place)}"
        if dropped or not any(row["key"] == key and row.get("pool_size") == mine for row in current):
            row = {"key": key, "id": key, "kind": POOL_KIND, "owner": locks.owner(place), "state": "recorded",
                   "pool_size": mine, "computed_at": time.time()}  # fmt: skip
            current = [*(other for other in current if other["key"] != key), row]
            _write(place, current)
    return min([mine, *(int(row.get("pool_size") or mine) for row in current if row.get("kind") == POOL_KIND)])


def _turn(
    rows: list[dict[str, Any]], mine: dict[str, Any], limit: int | None, room: Room, now: float
) -> tuple[str, bool]:
    """("", False) when *mine* may start now; else why it waits, and whether waiting cannot help.

    A job whose id is already running waits for that one and holds no place in line: at the head, it would hold up
    every other job of its kind for as long as the first one runs.
    """
    running_ids = {row["id"] for row in rows if row["state"] == "admitted"}
    if mine["id"] in running_ids:
        return f"{mine['id']} is already running", False
    same_kind = [row for row in rows if row.get("kind") == mine["kind"]]
    line = order([row for row in same_kind if row["id"] not in running_ids], now)
    if line and line[0]["key"] != mine["key"]:
        return "another job of its kind goes first", False
    running = sum(1 for row in same_kind if row["state"] == "admitted")
    if limit is not None and running >= max(1, limit):
        return f"all {max(1, limit)} places are in use", False
    disk = _short_disk(rows, mine["disk_bytes"], mine["drive"], room)  # the floor stands for every job
    memory = "" if disk else _short_memory(rows, mine["memory_bytes"], room, now)
    why = disk or memory
    if not why or (memory and limit is not None and running == 0):  # one job of a limited kind always gets memory
        return "", False
    holding = [row for row in rows if row["state"] == "admitted" and (row.get("disk_bytes") or row.get("memory_bytes"))]
    return why, not holding  # waiting helps only while a running job holds room it will give back


@contextmanager
def admitted(
    job_id: str,
    *,
    kind: str,
    files: int = 0,
    disk_bytes: int = 0,
    memory_bytes: int = 0,
    where: Path,
    limit: int | None = None,
    wait_s: float | None = None,
    room: Callable[[Path], Room] | None = None,
    root: Path | None = None,
    watch: Callable[[], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Hold a reservation for the ``with`` block: wait for this job's turn and its room, then give it back.

    Raises :class:`NotAdmitted` at once when the room is short and nothing is running that could give room back,
    and when it has waited *wait_s* seconds. *limit* caps how many jobs of *kind* run at once. A job's disk
    reservation always keeps the floor; only its memory is let through when no job of its limited kind runs.
    *watch* is called before each look at the line: whatever it raises ends the wait, and the row is given back.

    A ledger that is unavailable raises an ``OSError`` before the job starts, never a guess: ``TimeoutError`` (the file
    lock stayed held past ``WAIT_LIMIT_S``), ``PermissionError`` (the file stayed busy), or ``LedgerUnreadable`` (not
    a list of whole rows while a job of this process holds a row or another server's process that started before the
    file's last write lives), the last two from :mod:`~thomas.server.capacity_ledger_locks`. *wait_s* is timed on the
    monotonic clock, so a wall clock that steps never ends a wait early.
    The release in the ``finally`` logs such an error and never raises it over the job's own.
    """
    place = Path(root) if root is not None else folder()
    measured = room or measure
    mine = {"key": uuid.uuid4().hex, "id": str(job_id), "kind": str(kind), "owner": locks.owner(place),
            "files": int(files), "disk_bytes": int(disk_bytes), "memory_bytes": int(memory_bytes),
            "drive": _drive(Path(where)), "state": "waiting", "since": time.time(), "admitted_at": None}  # fmt: skip
    began = time.monotonic()  # the wait is timed on this; "since" is the wall clock the line is ordered by
    try:
        with locks.locked(place, NAME):
            others = _live(place)[0]
            locks.hold(mine["key"])  # held from just before its first write (no look can come between) to the finally
            _write(place, [*others, mine])
        while True:
            if watch is not None:
                watch()
            now_room = measured(Path(where))
            with locks.locked(place, NAME):
                current, dropped = _live(place)
                missing = not any(row["key"] == mine["key"] for row in current)
                if missing:
                    current.append(mine)
                now = time.time()
                why, hopeless = _turn(current, mine, limit, now_room, now)
                if not why:
                    mine.update(state="admitted", admitted_at=now)
                    current = [mine if row["key"] == mine["key"] else row for row in current]
                if dropped or missing or not why:
                    _write(place, current)
            if not why:
                break
            if hopeless:
                raise NotAdmitted(why, waited=False)
            if wait_s is not None and time.monotonic() - began >= wait_s:
                raise NotAdmitted(f"it waited {wait_s:g} s for its turn: {why}", waited=True)
            with _changed:
                _changed.wait(POLL_S)
        with _changed:
            _changed.notify_all()
        yield mine
    finally:
        locks.let_go(mine["key"])  # first: if the removal below fails, this process's next look drops the row
        try:
            with locks.locked(place, NAME):
                _write(place, [row for row in _live(place)[0] if row["key"] != mine["key"]])
        except OSError:  # never hides why the job ended; the row goes on the next look at the ledger
            log.exception("could not give back ledger row %s of %s", mine["key"], mine["id"])
        with _changed:
            _changed.notify_all()


def rows(root: Path | None = None) -> list[dict[str, Any]]:
    """The live rows of the ledger: waiting and admitted jobs, and each live server's recorded P."""
    place = Path(root) if root is not None else folder()
    with locks.locked(place, NAME):
        return [dict(row) for row in _live(place)[0]]


__all__ = [
    "FLOOR_BYTES",
    "GOES_NEXT_S",
    "NAME",
    "POLL_S",
    "POOL_KIND",
    "ROOT_ENV",
    "WARM_S",
    "NotAdmitted",
    "Room",
    "admitted",
    "disk_floor",
    "folder",
    "measure",
    "order",
    "pool_size",
    "refusal",
    "rows",
]
