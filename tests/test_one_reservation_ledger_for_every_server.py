"""One reservation ledger for every server on this machine (spec 2026-10-12 Part 1 item 5).

The caged server and your own server each ran their own check lock, so each could fill the same disk. Now both reserve
from one ledger: free disk minus what is promised never falls under 10 GiB, memory is counted against the reserve
once, waiting jobs go fewest files first with one place gained per minute waited, and each server records its own
pool size P there. Dead owners and the locks: test_the_reservation_ledger_drops_dead_owners.py.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from thomas.server import capacity_ledger as ledger
from thomas.server.precard import slot

GIB = 1024**3
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _the_ledger_is_this_tests_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ledger.ROOT_ENV, str(tmp_path / "unnamed-ledger"))  # never the machine's real ledger


def _room(free_gib: float, total_gib: float | None = None, available_gib: float | None = None) -> ledger.Room:
    def size(value: float | None) -> int | None:
        return None if value is None else int(value * GIB)

    return ledger.Room(int(free_gib * GIB), size(total_gib), size(available_gib))


def _row(**fields: object) -> dict:
    row = {"key": "k", "id": "j", "kind": "check", "owner": "o", "files": 0, "disk_bytes": 0, "memory_bytes": 0,
           "drive": "c:", "state": "admitted", "since": 0.0, "admitted_at": 0.0}  # fmt: skip
    return {**row, **fields}


def _waiting(key: str, files: int, since: float) -> dict:
    return _row(key=key, id=key, files=files, state="waiting", since=since, admitted_at=None)


def test_the_floor_is_one_number() -> None:
    assert ledger.disk_floor(8 * GIB) == slot.MIN_FREE_BYTES
    assert ledger.FLOOR_BYTES == ledger.disk_floor(100 * GIB) == 2 * GIB


def test_admission_keeps_free_disk_minus_reservations_at_or_above_the_floor() -> None:
    held = [_row(disk_bytes=4 * GIB)]

    why = ledger.refusal(held, disk_bytes=2 * GIB, memory_bytes=0, drive="c:", room=_room(6), now=100.0)

    assert "2 GB" in why
    assert ledger.refusal(held, disk_bytes=GIB, memory_bytes=0, drive="c:", room=_room(7), now=100.0) == ""
    other_drive = ledger.refusal(held, disk_bytes=2 * GIB, memory_bytes=0, drive="d:", room=_room(15), now=100.0)
    assert other_drive == "", "a reservation on another drive does not count"


def test_memory_is_admitted_against_the_reserve_once() -> None:
    held = [_row(memory_bytes=23 * GIB, admitted_at=0.0)]
    room = _room(100, 32, 30)

    assert ledger.refusal(held, disk_bytes=0, memory_bytes=GIB, drive="c:", room=room, now=1000.0) == ""
    assert ledger.refusal(held, disk_bytes=0, memory_bytes=2 * GIB, drive="c:", room=room, now=1000.0) != ""


def test_a_reservation_admitted_this_minute_counts_against_what_is_free() -> None:
    held = [_row(memory_bytes=int(1.5 * GIB), admitted_at=990.0)]
    room = _room(100, 32, 2)

    assert ledger.refusal(held, disk_bytes=0, memory_bytes=GIB, drive="c:", room=room, now=1000.0) != ""
    assert ledger.refusal(held, disk_bytes=0, memory_bytes=GIB, drive="c:", room=room, now=1100.0) == ""


def test_waiting_checks_go_fewest_files_first() -> None:
    rows = [_waiting("a", 100, 0.0), _waiting("b", 5, 0.0), _waiting("c", 40, 0.0)]

    assert [row["key"] for row in ledger.order(rows, 0.0)] == ["b", "c", "a"]


def test_aging_adds_one_priority_per_minute_waited() -> None:
    rows = [_waiting("a", 30, 0.0), _waiting("b", 20, 14 * 60.0)]

    assert [row["key"] for row in ledger.order(rows, 14 * 60.0)] == ["a", "b"], "30 files less 14 minutes beats 20"


def test_a_check_waiting_fifteen_minutes_goes_next() -> None:
    rows = [_waiting("a", 120, 0.0), _waiting("b", 1, 900.0)]

    assert [row["key"] for row in ledger.order(rows, 900.0)] == ["a", "b"]


def test_a_tie_goes_in_the_order_the_rows_were_written() -> None:
    rows = [_waiting("b", 0, 5.0), _waiting("a", 0, 5.0)]

    assert [row["key"] for row in ledger.order(rows, 5.0)] == ["b", "a"], "never by the row's random key"


def test_a_waiting_check_is_admitted_when_a_reservation_is_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger, "POLL_S", 0.05)
    root, inside, release, admitted_at = tmp_path / "ledger", threading.Event(), threading.Event(), []

    def hold() -> None:
        with ledger.admitted(
            "one", kind="check", disk_bytes=3 * GIB, where=tmp_path, room=lambda _w: _room(7), root=root
        ):
            inside.set()
            release.wait(5)

    def wait() -> None:
        with ledger.admitted(
            "two", kind="check", disk_bytes=3 * GIB, where=tmp_path, room=lambda _w: _room(7), root=root
        ):
            admitted_at.append(time.monotonic())

    holder = threading.Thread(target=hold)
    holder.start()
    assert inside.wait(5)
    waiter = threading.Thread(target=wait)
    waiter.start()
    time.sleep(0.3)
    assert admitted_at == [], "7 GB free with 3 promised: 3 more would breach the reserve"
    released = time.monotonic()
    release.set()
    holder.join(5)
    waiter.join(5)
    assert admitted_at and admitted_at[0] - released < 1.0


def _until(test: Callable[[], bool], within: float = 5.0) -> None:
    ends = time.monotonic() + within
    while not test():
        assert time.monotonic() < ends, "it never happened"
        time.sleep(0.01)


def test_waiting_checks_are_admitted_fewest_files_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "POLL_S", 0.02)
    root, release, admitted = tmp_path / "ledger", threading.Event(), []
    room = lambda _w: _room(7)  # noqa: E731 -- with 3 GB promised, no second check of 3 GB fits

    def hold() -> None:
        with ledger.admitted("held", kind="check", disk_bytes=3 * GIB, where=tmp_path, room=room, root=root):
            release.wait(10)

    def wait(name: str, files: int) -> None:
        with ledger.admitted(name, kind="check", files=files, disk_bytes=3 * GIB, where=tmp_path, room=room, root=root):
            admitted.append(name)

    holder = threading.Thread(target=hold)
    holder.start()
    _until(lambda: len(ledger.rows(root)) == 1)
    waiters: list[threading.Thread] = []
    for name, files in (("hundred", 100), ("five", 5), ("forty", 40)):
        waiters.append(threading.Thread(target=wait, args=(name, files)))
        waiters[-1].start()
        _until(lambda count=len(waiters): len(ledger.rows(root)) == 1 + count)
    assert admitted == []
    release.set()
    for thread in [holder, *waiters]:
        thread.join(10)
    assert admitted == ["five", "forty", "hundred"], "the line, not the order they asked in"


def test_a_short_disk_with_nothing_admitted_refuses_at_once_and_says_why(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    started = time.monotonic()

    with pytest.raises(ledger.NotAdmitted, match="2 GB") as refused:
        with ledger.admitted(
            "one", kind="check", disk_bytes=GIB, where=tmp_path, room=lambda _w: _room(2.5), root=root
        ):
            pass

    assert time.monotonic() - started < 0.5 and refused.value.waited is False
    assert ledger.rows(root) == []


def test_a_short_disk_beside_a_job_that_holds_no_room_still_refuses_at_once(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    room = lambda _w: _room(2.5)  # noqa: E731
    started = time.monotonic()

    with ledger.admitted("look", kind="look", where=tmp_path, limit=2, room=room, root=root):
        with pytest.raises(ledger.NotAdmitted, match="2 GB") as refused:
            with ledger.admitted("one", kind="check", disk_bytes=GIB, where=tmp_path, wait_s=5, room=room, root=root):
                pass

    assert time.monotonic() - started < 0.5 and refused.value.waited is False, "a job holding no room gives none back"


def test_one_job_id_is_never_admitted_twice_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "POLL_S", 0.05)
    root, marks = tmp_path / "ledger", []

    def job() -> None:
        with ledger.admitted("check:same", kind="check", where=tmp_path, room=lambda _w: _room(100), root=root):
            marks.append("in")
            time.sleep(0.2)
            marks.append("out")

    threads = [threading.Thread(target=job) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert marks == ["in", "out", "in", "out"]


def test_a_job_that_waits_too_long_is_told_it_waited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "POLL_S", 0.02)
    root = tmp_path / "ledger"
    room = lambda _w: _room(100)  # noqa: E731
    with ledger.admitted("first", kind="shard", where=tmp_path, limit=1, room=room, root=root):
        with pytest.raises(ledger.NotAdmitted) as late:
            with ledger.admitted("second", kind="shard", where=tmp_path, limit=1, wait_s=0.2, room=room, root=root):
                pass
    assert late.value.waited is True


CHILD = r"""
import sys, threading, time
from pathlib import Path
from thomas.server import capacity_ledger as ledger
root, log, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
ledger.POLL_S = 0.05
spans = []
def job(n):
    room = lambda _w: ledger.Room(10 * 1024**3, None, None, 100 * 1024**3)
    with ledger.admitted(f"{name}-{n}", kind="check", disk_bytes=3 * 1024**3, where=root, room=room, root=root):
        start = time.time()
        time.sleep(0.3)
        spans.append(f"{name} {start} {time.time()}")
threads = [threading.Thread(target=job, args=(n,)) for n in range(5)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
log.write_text("\n".join(spans), encoding="utf-8")
"""


def test_two_server_processes_never_breach_the_floor(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    logs = {name: tmp_path / f"{name}.log" for name in ("a", "b")}
    children = [
        subprocess.Popen([sys.executable, "-c", CHILD, str(root), str(log), name], cwd=REPO)
        for name, log in logs.items()
    ]
    for child in children:
        assert child.wait(180) == 0
    spans = [line.split() for log in logs.values() for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(spans) == 10 and {name for name, _, _ in spans} == {"a", "b"}
    edges = sorted([(float(start), 1) for _, start, _ in spans] + [(float(end), -1) for _, _, end in spans])
    running = most = 0
    for _, step in edges:
        running += step
        most = max(most, running)
    assert 2 <= most <= 3, "10 GB free and 3 GB each: at most 3 at once across both processes"


HOLDS_P = r"""
import sys, time
from pathlib import Path
from thomas.server import capacity_ledger as ledger
root, ready, done = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
assert ledger.pool_size(3, root=root) == 3
ready.write_text("x", encoding="utf-8")
ends = time.time() + 60
while not done.exists() and time.time() < ends:
    time.sleep(0.05)
"""


def test_p_is_the_smallest_any_live_server_computed(tmp_path: Path) -> None:
    root, ready, done = tmp_path / "ledger", tmp_path / "ready", tmp_path / "done"
    child = subprocess.Popen([sys.executable, "-c", HOLDS_P, str(root), str(ready), str(done)], cwd=REPO)
    try:
        _until(lambda: ready.exists() or child.poll() is not None, within=120)
        assert ready.exists(), "the other server never recorded its P"
        assert ledger.pool_size(5, root=root) == 3, "the other server's smaller P holds for every shard"
        assert ledger.pool_size(2, root=root) == 2
    finally:
        done.write_text("x", encoding="utf-8")
        assert child.wait(60) == 0
    assert ledger.pool_size(5, root=root) == 5, "a P whose server is gone no longer counts"


def test_a_waiting_job_is_called_off_by_what_its_watch_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "POLL_S", 0.02)
    root, looks = tmp_path / "ledger", []
    room = lambda _w: _room(100)  # noqa: E731

    def watch() -> None:
        looks.append(time.monotonic())
        if len(looks) >= 3:
            raise LookupError("called off while it waited")

    with ledger.admitted("first", kind="look", where=tmp_path, limit=1, room=room, root=root):
        with pytest.raises(LookupError):
            with ledger.admitted("second", kind="look", where=tmp_path, limit=1, room=room, root=root, watch=watch):
                pass
        assert [row["id"] for row in ledger.rows(root)] == ["first"], "the row it waited in is given back"
    assert len(looks) == 3
