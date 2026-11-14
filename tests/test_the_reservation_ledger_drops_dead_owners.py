"""The reservation ledger drops a row nobody can still be using, and its locks keep two servers apart.

A server that dies takes its reserved room with it: its owner lock file can then be locked by anyone, so its rows
go. A row of a live server that none of its jobs holds (the write that gave it back failed) goes too, so one failed
write never blocks a kind of job on both servers until a restart. These tests start real second processes, because
the file lock, the owner lock files and what Windows does when a process ends cannot be shown with threads.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from thomas.server import capacity_ledger as ledger
from thomas.server import capacity_ledger_locks as locks
from thomas.server import hand_in_hold_store, thomas_project

GIB = 1024**3
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _the_ledger_is_this_tests_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A call that forgot its root still lands in the test's folder, never in the machine's real ledger."""
    monkeypatch.setenv(ledger.ROOT_ENV, str(tmp_path / "unnamed-ledger"))


def _room(free_gib: float, total_gib: float | None = None, available_gib: float | None = None) -> ledger.Room:
    def size(value: float | None) -> int | None:
        return None if value is None else int(value * GIB)

    return ledger.Room(int(free_gib * GIB), size(total_gib), size(available_gib))


def _until(test: Callable[[], bool], within: float = 5.0) -> None:
    ends = time.monotonic() + within
    while not test():
        assert time.monotonic() < ends, "it never happened"
        time.sleep(0.01)


def test_a_row_whose_release_failed_is_dropped_and_the_jobs_own_error_still_reaches_its_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ledger"
    room = lambda _w: _room(100)  # noqa: E731
    real, releasing = ledger._write, []

    def full_disk_once(place: Path, rows: list[dict]) -> None:
        if releasing == ["now"]:
            releasing.append("failed")
            raise OSError(28, "No space left on device")
        real(place, rows)

    monkeypatch.setattr(ledger, "_write", full_disk_once)
    assert ledger.pool_size(3, root=root) == 3
    with pytest.raises(ValueError, match="the job's own error"):
        with ledger.admitted("first", kind="shard", where=tmp_path, limit=1, room=room, root=root):
            releasing.append("now")
            raise ValueError("the job's own error")
    assert releasing == ["now", "failed"], "the write that gives the row back failed"

    with ledger.admitted("second", kind="shard", where=tmp_path, limit=1, wait_s=2, room=room, root=root):
        assert [row["id"] for row in ledger.rows(root) if row["kind"] != ledger.POOL_KIND] == ["second"]
    assert [row["kind"] for row in ledger.rows(root)] == [ledger.POOL_KIND], "this process's P stays for its life"


DIES = r"""
import os, sys
from pathlib import Path
from thomas.server import capacity_ledger as ledger
root = Path(sys.argv[1])
room = lambda _w: ledger.Room(20 * 1024**3, None, None)
held = ledger.admitted("dies", kind="check", disk_bytes=8 * 1024**3, where=root, room=room, root=root)
held.__enter__()
os._exit(0)
"""


def test_a_row_left_by_a_dead_server_is_dropped(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    assert subprocess.run([sys.executable, "-c", DIES, str(root)], cwd=REPO, timeout=120).returncode == 0
    left = json.loads((root / ledger.NAME).read_text(encoding="utf-8"))
    assert [row["id"] for row in left] == ["dies"], "the process ended without giving its room back"

    with ledger.admitted("lives", kind="check", disk_bytes=8 * GIB, where=tmp_path, wait_s=5,
                         room=lambda _w: _room(20), root=root):  # fmt: skip
        assert [row["id"] for row in ledger.rows(root)] == ["lives"]


OWNS = r"""
import os, sys
from pathlib import Path
from thomas.server import capacity_ledger_locks as locks
print(locks.owner(Path(sys.argv[1])), flush=True)
os._exit(0)
"""


def test_a_process_holds_its_owner_lock_file_for_its_life_and_a_dead_ones_is_removed(tmp_path: Path) -> None:
    place = tmp_path / "ledger"
    mine = locks.owner(place)
    assert re.fullmatch(rf"owner-{os.getpid()}-[0-9a-f]{{8}}", mine) and locks.owner(place) == mine
    with open(place / f"{mine}.lock", "a+b") as other_handle:
        assert locks.lock_file(other_handle, wait=False) is False, "this process still holds its own"
    assert locks.owner_alive(place, mine) is True

    ran = subprocess.run(
        [sys.executable, "-c", OWNS, str(place)], cwd=REPO, timeout=120, capture_output=True, text=True
    )
    gone = ran.stdout.strip()
    assert ran.returncode == 0 and gone.startswith("owner-") and gone != mine and (place / f"{gone}.lock").is_file()
    assert locks.owner_alive(place, gone) is False, "the process that held it has ended"
    assert not (place / f"{gone}.lock").exists(), "a dead owner's lock file is cleared away"
    assert locks.owner_alive(place, "owner-1-ffffffff") is False and locks.owner_alive(place, "elsewhere") is False


def test_a_live_process_keeps_the_rows_a_job_holds_and_the_standing_ones_and_drops_the_rest(tmp_path: Path) -> None:
    place = tmp_path / "ledger"
    me = locks.owner(place)

    def row(key: str, kind: str, owner: str = me) -> dict:
        return {"key": key, "kind": kind, "owner": owner}

    found = [
        row("held", "check"),
        row("let-go", "check"),
        row("p", ledger.POOL_KIND),
        row("gone", "check", "owner-1-0"),
    ]
    locks.hold("held")
    try:
        kept, dropped = locks.alive(place, found, standing=ledger.POOL_KIND)
    finally:
        locks.let_go("held")
    assert [kept_row["key"] for kept_row in kept] == ["held", "p"] and dropped is True
    kept, dropped = locks.alive(place, found[:1], standing=ledger.POOL_KIND)
    assert kept == [] and dropped is True, "a job that let its row go no longer keeps it"
    assert locks.alive(place, found[2:3], standing=ledger.POOL_KIND) == (found[2:3], False)


def test_a_write_lands_while_a_reader_still_has_the_file_open(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    assert ledger.pool_size(3, root=root) == 3
    reader = open(root / ledger.NAME, "rb")  # noqa: SIM115 -- closed by the timer, as a slow reader would
    closer = threading.Timer(0.15, reader.close)
    closer.start()

    assert ledger.pool_size(2, root=root) == 2, "Windows refuses to replace an open file; the write tries again"

    closer.join()
    assert [row["pool_size"] for row in ledger.rows(root)] == [2]


def test_the_ledger_its_file_lock_and_every_owner_lock_file_live_in_the_one_folder_the_servers_share(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = tmp_path / "named"
    monkeypatch.setenv(ledger.ROOT_ENV, str(named))
    assert ledger.folder() == named
    with ledger.admitted("job", kind="check", where=tmp_path, room=lambda _w: _room(100)):
        assert sorted(path.name for path in named.iterdir()) == sorted(
            [ledger.NAME, f"{ledger.NAME}.lock", f"{locks.owner(named)}.lock"]
        )

    monkeypatch.delenv(ledger.ROOT_ENV)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: tmp_path / "catalog")
    assert ledger.folder() == hand_in_hold_store.path(tmp_path / "catalog").parent, "beside hand_in_holds.json"


HOLDS_LOCK = r"""
import sys, time
from pathlib import Path
from thomas.server import capacity_ledger_locks as locks
place, name, ready, done = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
with locks.locked(place, name):
    ready.write_text("x", encoding="utf-8")
    ends = time.time() + 60
    while not done.exists() and time.time() < ends:
        time.sleep(0.02)
"""


def _holder(tmp_path: Path) -> tuple[Path, Path, Path, subprocess.Popen]:
    place, ready, done = tmp_path / "ledger", tmp_path / "ready", tmp_path / "done"
    child = subprocess.Popen([sys.executable, "-c", HOLDS_LOCK, str(place), "x", str(ready), str(done)], cwd=REPO)
    _until(lambda: ready.exists() or child.poll() is not None, within=120)
    assert ready.exists(), "the other process never took the lock"
    return place, ready, done, child


def test_the_file_lock_refuses_a_second_process_and_gives_up_after_its_wait_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    place, _ready, done, child = _holder(tmp_path)
    monkeypatch.setattr(locks, "WAIT_LIMIT_S", 0.3)
    try:
        with open(place / "x.lock", "a+b") as handle:
            assert locks.lock_file(handle, wait=False) is False
            started = time.monotonic()
            with pytest.raises(TimeoutError, match="stayed locked"):
                locks.lock_file(handle, wait=True)
            assert 0.25 <= time.monotonic() - started < 5
        with pytest.raises(OSError):  # TimeoutError is an OSError: the ledger's release logs it, never raises it
            with locks.locked(place, "x"):
                pass
    finally:
        done.write_text("x", encoding="utf-8")
        assert child.wait(60) == 0
    with locks.locked(place, "x"):
        pass


def test_a_second_process_waits_for_the_file_lock_and_then_takes_it(tmp_path: Path) -> None:
    place, _ready, done, child = _holder(tmp_path)
    letting_go = threading.Timer(0.5, done.write_text, ["x", "utf-8"])
    letting_go.start()
    started = time.monotonic()
    try:
        with locks.locked(place, "x"):
            waited = time.monotonic() - started
    finally:
        letting_go.cancel()
        done.write_text("x", encoding="utf-8")
        assert child.wait(60) == 0
    assert 0.3 <= waited < 20, "it waited for the other process, not for the 60 s limit"


BUMPS = r"""
import sys
from pathlib import Path
from thomas.server import capacity_ledger_locks as locks
place, counter = Path(sys.argv[1]), Path(sys.argv[2])
for _ in range(40):
    with locks.locked(place, "counter"):
        counter.write_text(str(int(counter.read_text(encoding="utf-8")) + 1), encoding="utf-8")
"""


def test_three_processes_never_hold_the_file_lock_together(tmp_path: Path) -> None:
    place, counter = tmp_path / "ledger", tmp_path / "counter"
    counter.write_text("0", encoding="utf-8")
    children = [subprocess.Popen([sys.executable, "-c", BUMPS, str(place), str(counter)], cwd=REPO) for _ in range(3)]
    for child in children:
        assert child.wait(180) == 0
    assert counter.read_text(encoding="utf-8") == "120", "a read-add-write under the lock lost no update"


def test_a_process_that_cannot_lock_its_own_owner_file_publishes_no_rows_under_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    place = tmp_path / "ledger"
    with monkeypatch.context() as broken:
        broken.setattr(locks, "lock_file", lambda handle, *, wait: False)
        with pytest.raises(OSError, match="own owner file"):
            with ledger.admitted("job", kind="check", where=tmp_path, room=lambda _w: _room(100), root=place):
                pass
    assert not (place / ledger.NAME).exists() and not list(place.glob("owner-*.lock")), "every peer would drop them"
    with ledger.admitted("job", kind="check", where=tmp_path, room=lambda _w: _room(100), root=place) as row:
        assert row["state"] == "admitted" and row["owner"] == locks.owner(place)


def test_a_limited_kind_keeps_the_disk_floor_and_only_its_memory_gets_the_first_job_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger, "POLL_S", 0.02)
    root, room = tmp_path / "ledger", lambda _w: _room(7)  # noqa: E731
    with pytest.raises(ledger.NotAdmitted, match="2 GB") as refused:
        with ledger.admitted("big", kind="build", limit=2, disk_bytes=6 * GIB, where=tmp_path, room=room, root=root):
            pass
    assert refused.value.waited is False and ledger.rows(root) == [], "nothing of its kind runs, the floor still holds"
    with ledger.admitted("check", kind="check", disk_bytes=3 * GIB, where=tmp_path, room=room, root=root):
        with pytest.raises(ledger.NotAdmitted) as late:
            with ledger.admitted("big", kind="build", limit=4, disk_bytes=3 * GIB, wait_s=0.2, where=tmp_path,
                                 room=room, root=root):  # fmt: skip
                pass
        assert late.value.waited is True, "7 GB free, 3 promised, 3 more would leave 1: it waits for the check"
    short_of_memory = lambda _w: ledger.Room(100 * GIB, 32 * GIB, GIB // 2)  # noqa: E731
    with ledger.admitted("wide", kind="build", limit=2, memory_bytes=GIB, where=tmp_path, room=short_of_memory,
                         root=root) as row:  # fmt: skip
        assert row["state"] == "admitted", "the first job of a limited kind still gets through short of memory"
