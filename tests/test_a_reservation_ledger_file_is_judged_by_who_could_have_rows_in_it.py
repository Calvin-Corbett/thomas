"""A reservation ledger file nobody could have rows in is replaced; one a live server might is left alone.

Review of the whole change, finding I1: after a power cut left ``reservations.json`` empty, two live servers each
saw the other as a possible owner of rows in it, so neither ever moved it aside and every shard was refused until one
ended. A server now counts only when it started before the file was last written, since a process started later cannot
have written into it. And every write is flushed to the disk before it replaces the file, so a power cut no longer
leaves a renamed but empty one. Finding M1: a row with a field missing or of the wrong type makes the file
unreadable the same way, and is never a KeyError in the middle of a job. Sibling of
``test_an_unreadable_reservation_ledger_is_never_taken_for_an_empty_one.py``, which stays under the 300-line cap.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from thomas.server import capacity_ledger as ledger
from thomas.server import capacity_ledger_locks as locks

GIB = 1024**3


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


@contextmanager
def _live_owner(root: Path, name: str) -> Iterator[None]:
    """A server process that lives: its owner lock file exists and this test holds its lock until the block ends."""
    root.mkdir(parents=True, exist_ok=True)
    with open(root / f"{name}.lock", "a+b") as handle:
        assert locks.lock_file(handle, wait=False)
        try:
            yield
        finally:
            locks.unlock_file(handle)


def _written(root: Path, text: str, at: float) -> None:
    """The ledger file holding *text*, last written at time *at*."""
    (root / ledger.NAME).write_text(text, encoding="utf-8")
    os.utime(root / ledger.NAME, (at, at))


def test_servers_that_both_started_after_the_file_was_corrupted_move_it_aside(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    root.mkdir()
    _written(root, "", time.time() - 3600)  # a power cut an hour ago left it empty; both servers started since

    with _live_owner(root, "owner-2-aaaaaaaa"), _live_owner(root, "owner-3-bbbbbbbb"):
        assert ledger.pool_size(3, root=root) == 3, "neither can have rows in it, so the ledger starts empty"
        assert [row["kind"] for row in ledger.rows(root)] == [ledger.POOL_KIND]
        (aside,) = root.glob(f"{ledger.NAME}.corrupt-*")
        assert aside.read_bytes() == b"" and (root / "owner-2-aaaaaaaa.lock").exists(), "live owners are left alone"


def test_a_server_that_started_before_the_file_was_corrupted_may_have_rows_in_it(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    with _live_owner(root, "owner-2-aaaaaaaa"):
        first_lock = (root / "owner-2-aaaaaaaa.lock").stat()
        _written(root, "{not json", first_lock.st_mtime)
        written = (root / ledger.NAME).stat().st_mtime
        assert min(first_lock.st_mtime, getattr(first_lock, "st_birthtime", first_lock.st_mtime)) <= written, (
            "the first owner's lock file must be at or before the ledger write"
        )
        with pytest.raises(locks.LedgerUnreadable):
            ledger.rows(root)
        later = time.monotonic()
        _until(lambda: time.monotonic() > later + 0.1)  # allow a distinct file timestamp for the second owner
        with _live_owner(root, "owner-3-bbbbbbbb"):  # started after the write, which changes nothing for the first
            second_lock = (root / "owner-3-bbbbbbbb.lock").stat()
            assert min(second_lock.st_mtime, getattr(second_lock, "st_birthtime", second_lock.st_mtime)) > written, (
                "the second owner's lock file must be after the ledger write"
            )
            with pytest.raises(locks.LedgerUnreadable):
                ledger.pool_size(3, root=root)
    assert (root / ledger.NAME).read_text(encoding="utf-8") == "{not json" and not list(root.glob("*.corrupt-*"))


GOOD = {"key": "k", "id": "job", "kind": "shard", "owner": "owner-2-aaaaaaaa", "state": "waiting", "files": 3,
        "disk_bytes": 0, "memory_bytes": 5, "drive": "c:", "since": 1.5, "admitted_at": None}  # fmt: skip
BAD_ROWS = [
    pytest.param({k: v for k, v in GOOD.items() if k != "id"}, id="no id"),
    pytest.param({k: v for k, v in GOOD.items() if k != "state"}, id="no state"),
    pytest.param({k: v for k, v in GOOD.items() if k != "key"}, id="no key"),
    pytest.param({k: v for k, v in GOOD.items() if k != "owner"}, id="no owner"),
    pytest.param({**GOOD, "state": 3}, id="state is a number"),
    pytest.param({**GOOD, "since": "soon"}, id="since is text"),
    pytest.param({**GOOD, "files": [1]}, id="files is a list"),
    pytest.param({**GOOD, "memory_bytes": True}, id="memory is a boolean"),
    pytest.param({**GOOD, "disk_bytes": float("inf")}, id="disk is infinite"),
    pytest.param({**GOOD, "admitted_at": float("nan")}, id="admitted_at is not a number"),
    pytest.param({**GOOD, "kind": "pool_size", "state": "recorded", "pool_size": "twelve"}, id="P is text"),
    pytest.param("just text", id="a row that is text"),
    pytest.param(None, id="a row that is nothing"),
]


@pytest.mark.parametrize("bad", BAD_ROWS)
def test_a_row_missing_a_field_or_of_the_wrong_type_makes_the_file_unreadable_for_a_live_server(
    tmp_path: Path, bad: object
) -> None:
    root = tmp_path / "ledger"
    with _live_owner(root, "owner-2-aaaaaaaa"):
        text = json.dumps([GOOD, bad])
        _written(root, text, time.time() + 60)  # written after that server started: its rows may be in it
        admit = ledger.admitted("mine", kind="shard", where=tmp_path, room=lambda _w: _room(20), root=root)
        for look in (lambda: ledger.rows(root), lambda: ledger.pool_size(3, root=root), admit.__enter__):
            with pytest.raises(locks.LedgerUnreadable):  # an OSError for the ledger's callers, never a KeyError
                look()
    assert (root / ledger.NAME).read_text(encoding="utf-8") == text and not list(root.glob("*.corrupt-*"))


@pytest.mark.parametrize("bad", BAD_ROWS)
def test_a_row_missing_a_field_is_moved_aside_with_its_file_when_nobody_else_has_rows_in_it(
    tmp_path: Path, bad: object
) -> None:
    root = tmp_path / "ledger"
    root.mkdir()
    text = json.dumps([GOOD, bad])
    _written(root, text, time.time())

    assert ledger.rows(root) == []

    (aside,) = root.glob(f"{ledger.NAME}.corrupt-*")
    assert aside.read_text(encoding="utf-8") == text and ledger.pool_size(3, root=root) == 3


def test_a_row_with_every_field_is_still_read(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    recorded = {**GOOD, "key": "p", "kind": "pool_size", "state": "recorded", "pool_size": 4, "computed_at": 2}
    with _live_owner(root, "owner-2-aaaaaaaa"):
        _written(root, json.dumps([GOOD, recorded]), time.time())
        assert [row["key"] for row in ledger.rows(root)] == ["k", "p"] and not list(root.glob("*.corrupt-*"))


def test_a_write_is_flushed_to_the_disk_before_it_replaces_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NTFS keeps a rename whose data it had not yet written: a power cut left reservations.json empty."""
    root, order = tmp_path / "ledger", []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(descriptor: int) -> None:
        order.append("fsync")
        real_fsync(descriptor)

    def replace(source: object, target: object) -> None:
        order.append("replace")
        assert [row["kind"] for row in json.loads(Path(str(source)).read_text(encoding="utf-8"))] == [ledger.POOL_KIND]
        real_replace(source, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    assert ledger.pool_size(3, root=root) == 3
    assert order == ["fsync", "replace"], "the rows reach the disk, then the file takes the ledger's place"

    def broken(_descriptor: int) -> None:
        raise OSError(5, "the disk would not take it")

    before = (root / ledger.NAME).read_bytes()
    monkeypatch.setattr(os, "fsync", broken)
    with pytest.raises(OSError, match="would not take"):
        ledger.pool_size(2, root=root)
    assert (root / ledger.NAME).read_bytes() == before, "a write that was not made durable never replaces the file"
    assert [path.name for path in root.iterdir() if path.name.endswith(".tmp")] == [], "and leaves no temporary file"
