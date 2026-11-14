"""A reservation ledger that cannot be read is never taken for an empty one (review of Task 11, finding I1).

A read that failed came back as "no rows", and the next write put that back: another server's admitted reservations
were erased and an 8 GiB check was admitted on 16 GiB free beside the 8 GiB already promised, leaving no reserve.
Now a busy file is read again and then the error is raised, a file that is not a list of rows raises
while another server's process lives and is moved aside when none does, and nothing is written after a failed read.
The other server here is a real second process holding a reservation.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from thomas.server import capacity_ledger as ledger
from thomas.server import capacity_ledger_locks as locks

GIB = 1024**3
REPO = Path(__file__).resolve().parents[1]
NESTED = pytest.param("[" * 100_000 + "]" * 100_000, id="nested")  # overflows the JSON parser: RecursionError


@pytest.fixture(autouse=True)
def _the_ledger_is_this_tests_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ledger.ROOT_ENV, str(tmp_path / "unnamed-ledger"))  # never the machine's real ledger


def _room(free_gib: float) -> ledger.Room:
    return ledger.Room(int(free_gib * GIB), None, None)


def _until(test: Callable[[], bool], within: float = 5.0) -> None:
    ends = time.monotonic() + within
    while not test():
        assert time.monotonic() < ends, "it never happened"
        time.sleep(0.01)


PEER = r"""
import sys, time
from pathlib import Path
from thomas.server import capacity_ledger as ledger
root, ready, done = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
room = lambda _w: ledger.Room(20 * 1024**3, None, None)
with ledger.admitted("peer", kind="check", disk_bytes=8 * 1024**3, where=root, room=room, root=root):
    ready.write_text("x", encoding="utf-8")
    ends = time.time() + 60
    while not done.exists() and time.time() < ends:
        time.sleep(0.02)
"""


@contextmanager
def _peer(tmp_path: Path) -> Iterator[Path]:
    """The ledger's folder while another server's process holds an 8 GiB reservation in it."""
    root, ready, done = tmp_path / "ledger", tmp_path / "ready", tmp_path / "done"
    child = subprocess.Popen([sys.executable, "-c", PEER, str(root), str(ready), str(done)], cwd=REPO)
    try:
        _until(lambda: ready.exists() or child.poll() is not None, within=120)
        assert ready.exists(), "the other server never reserved"
        yield root
    finally:
        done.write_text("x", encoding="utf-8")
        assert child.wait(60) == 0


@pytest.mark.skipif(os.name != "nt", reason="only Windows lets a handle hold a file without sharing it for reading")
def test_a_busy_ledger_file_is_read_again_and_never_taken_for_an_empty_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import _winapi

    monkeypatch.setattr(ledger, "POLL_S", 0.02)

    def hold_busy() -> int:
        return _winapi.CreateFile(str(root / ledger.NAME), _winapi.GENERIC_READ, 0, 0, _winapi.OPEN_EXISTING, 0, 0)

    with _peer(tmp_path) as root:
        with monkeypatch.context() as quick:
            quick.setattr(locks, "READ_WAIT_S", 0.005)  # gives up after about 0.05 s, long before the file is free
            closer = threading.Timer(0.4, _winapi.CloseHandle, [hold_busy()])
            closer.start()
            with pytest.raises(PermissionError):
                ledger.pool_size(3, root=root)  # not [] and a write: the rename would have waited for the handle
            closer.join()
        assert [row["id"] for row in ledger.rows(root)] == ["peer"], "nothing was written over the other server's row"
        with pytest.raises(ledger.NotAdmitted) as refused:
            with ledger.admitted("mine", kind="check", disk_bytes=8 * GIB, where=tmp_path, wait_s=0.3,
                                 room=lambda _w: _room(16), root=root):  # fmt: skip
                pass
        assert "2 GB" in str(refused.value), "two 8 GiB jobs leave no reserve of 16 GiB"

        threading.Timer(0.05, _winapi.CloseHandle, [hold_busy()]).start()
        assert ledger.pool_size(3, root=root) == 3, "a file busy for a moment is waited out"
        assert sorted(row["kind"] for row in ledger.rows(root)) == ["check", ledger.POOL_KIND]


@pytest.mark.parametrize("text", ["{not json", NESTED])
def test_a_file_that_is_not_a_list_is_left_alone_while_another_server_runs(tmp_path: Path, text: str) -> None:
    with _peer(tmp_path) as root:
        path = root / ledger.NAME
        before = path.read_bytes()
        path.write_text(text, encoding="utf-8")

        def admit() -> None:
            with ledger.admitted("mine", kind="check", where=tmp_path, room=lambda _w: _room(20), root=root):
                pass

        try:
            for look in (lambda: ledger.rows(root), lambda: ledger.pool_size(3, root=root), admit):
                with pytest.raises(locks.LedgerUnreadable):
                    look()
            assert path.read_text(encoding="utf-8") == text and not list(root.glob("*.corrupt-*"))
        finally:
            path.write_bytes(before)
        assert [row["id"] for row in ledger.rows(root)] == ["peer"], "the other server's reservation is still there"


@pytest.mark.parametrize("text", ["{not json", '{"a": "list was expected"}', "", NESTED])
def test_a_file_that_is_not_a_list_is_moved_aside_when_nothing_else_has_rows_in_it(tmp_path: Path, text: str) -> None:
    root = tmp_path / "ledger"
    root.mkdir()
    (root / "owner-1-deadbeef.lock").write_bytes(b"")  # a server that died: nobody holds this lock
    (root / ledger.NAME).write_text(text, encoding="utf-8")

    assert ledger.rows(root) == []

    (aside,) = root.glob(f"{ledger.NAME}.corrupt-*")
    assert aside.read_text(encoding="utf-8") == text and not (root / ledger.NAME).exists()
    (root / ledger.NAME).write_text(text, encoding="utf-8")
    assert ledger.rows(root) == [] and len(list(root.glob(f"{ledger.NAME}.corrupt-*"))) == 2, "none is overwritten"
    assert ledger.pool_size(3, root=root) == 3 and [row["kind"] for row in ledger.rows(root)] == [ledger.POOL_KIND]


def test_the_first_job_after_a_bad_file_is_admitted_once_it_is_moved_aside(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    root.mkdir()
    (root / ledger.NAME).write_text("{not json", encoding="utf-8")

    with ledger.admitted("first", kind="check", where=tmp_path, room=lambda _w: _room(20), root=root) as row:
        assert row["state"] == "admitted" and len(list(root.glob(f"{ledger.NAME}.corrupt-*"))) == 1


def test_a_file_that_is_not_a_list_is_left_alone_while_a_job_of_this_process_runs(tmp_path: Path) -> None:
    root, room = tmp_path / "ledger", lambda _w: _room(20)  # noqa: E731
    with ledger.admitted("running", kind="check", disk_bytes=8 * GIB, where=tmp_path, room=room, root=root):
        before = (root / ledger.NAME).read_bytes()
        (root / ledger.NAME).write_text("{corrupt", encoding="utf-8")
        with pytest.raises(locks.LedgerUnreadable):
            ledger.rows(root)
        with pytest.raises(locks.LedgerUnreadable):  # 8 GiB beside the running 8 GiB would leave 4 GiB of 20
            with ledger.admitted("second", kind="check", disk_bytes=8 * GIB, where=tmp_path, wait_s=0.2,
                                 room=room, root=root):  # fmt: skip
                pass
        assert (root / ledger.NAME).read_text(encoding="utf-8") == "{corrupt" and not list(root.glob("*.corrupt-*"))
        (root / ledger.NAME).write_bytes(before)
        assert [row["id"] for row in ledger.rows(root)] == ["running"]

    (root / ledger.NAME).write_text("{corrupt", encoding="utf-8")
    assert ledger.rows(root) == [], "with no job holding a row, nothing is lost by moving it aside"
