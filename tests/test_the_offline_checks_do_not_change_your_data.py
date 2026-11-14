"""BootDoctor's offline checks look at your data without changing it, and never call a busy file damaged.

A file called damaged is one `check --quarantine` moves aside, so the line between "damaged" and "in use" matters:
a database another program holds locked is reported as unreadable and left alone.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import thomas.bootdoctor.__main__ as bd_main
from tests._bootdoctor_fakes import ThomasServer, isolate_offline_checks, listener
from thomas.core import boot_checks


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)


def _database(path: Path, *, wal: bool = False, damaged_body: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    if wal:
        con.execute("pragma journal_mode=wal")
    con.execute("create table t (x)")
    con.executemany("insert into t values (?)", [(n,) for n in range(2000)])
    con.commit()
    con.close()
    if damaged_body:
        # A valid header with garbage pages behind it: only the full integrity check can tell.
        data = bytearray(path.read_bytes())
        data[4096:] = b"\x07" * (len(data) - 4096)
        path.write_bytes(bytes(data))
    return path


def _snapshot(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


def test_checking_a_database_changes_neither_its_bytes_nor_its_modified_time(tmp_path: Path) -> None:
    plain = _database(tmp_path / "data" / ".thomas" / "plain.sqlite3")
    journaled = _database(tmp_path / "data" / ".thomas" / "wal.sqlite3", wal=True)
    before = {path: _snapshot(path) for path in (plain, journaled)}

    assert boot_checks.database_state(plain)[0] == "ok"
    assert boot_checks.database_state(journaled)[0] == "ok"
    rows, damaged = boot_checks.run_offline_checks(tmp_path, memory_root=tmp_path / "mem")

    assert damaged == []
    assert {path: _snapshot(path) for path in before} == before
    # SQLite may leave empty -wal/-shm files beside a WAL database; nothing else may appear.
    allowed = {"plain.sqlite3", "wal.sqlite3", "wal.sqlite3-wal", "wal.sqlite3-shm"}
    assert {p.name for p in plain.parent.iterdir()} <= allowed


def test_databases_are_opened_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _database(tmp_path / "data" / ".thomas" / "runs.sqlite3")
    opened: list[str] = []
    real_connect = sqlite3.connect

    def spy(target, *args, **kwargs):
        opened.append(str(target))
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)

    boot_checks.database_state(db)

    assert opened
    assert all("mode=ro" in target for target in opened), opened


def test_no_probe_file_is_left_behind(tmp_path: Path) -> None:
    folder = tmp_path / "state"
    folder.mkdir()

    assert boot_checks.check_writable(folder)[1] == "ok"
    boot_checks.run_offline_checks(tmp_path, memory_root=tmp_path / "mem")

    assert list(folder.iterdir()) == []
    assert list(tmp_path.rglob(".bootdoctor_write_*")) == []


def test_a_database_another_program_holds_locked_is_unreadable_and_is_never_moved(tmp_path: Path, capsys) -> None:
    db = _database(tmp_path / "data" / ".thomas" / "runs.sqlite3")
    holder = sqlite3.connect(db, timeout=0.1, isolation_level=None)
    holder.execute("begin exclusive")
    try:
        state, detail = boot_checks.database_state(db)
        exit_code = bd_main.main(["check", "--quarantine", "--root", str(tmp_path), "--port", "22057"])
    finally:
        holder.rollback()
        holder.close()

    assert state == "unreadable"
    assert "locked" in detail
    assert exit_code == 0  # a busy file is a warning, not damage
    assert db.exists()
    assert list(db.parent.glob("*.corrupt-*")) == []
    assert "[warn] database_integrity:" in capsys.readouterr().out


def test_a_running_thomas_blocks_quarantine_and_the_damaged_file_stays_where_it_is(tmp_path: Path, capsys) -> None:
    # A Thomas that has its databases open must not have them renamed from under it: the repair says so and moves nothing.
    damaged = tmp_path / "data" / ".thomas" / "runs.sqlite3"
    damaged.parent.mkdir(parents=True)
    damaged.write_bytes(b"not a database at all" * 5)

    with listener(ThomasServer) as port:
        exit_code = bd_main.main(["check", "--quarantine", "--root", str(tmp_path), "--port", str(port)])

    assert exit_code == 2
    assert damaged.exists()
    assert list(damaged.parent.glob("*.corrupt-*")) == []
    assert "runtime detected" in capsys.readouterr().out


def test_a_plain_check_still_runs_beside_a_running_thomas(tmp_path: Path, capsys) -> None:
    damaged = tmp_path / "data" / ".thomas" / "runs.sqlite3"
    damaged.parent.mkdir(parents=True)
    damaged.write_bytes(b"not a database at all" * 5)

    with listener(ThomasServer) as port:
        exit_code = bd_main.main(["check", "--root", str(tmp_path), "--port", str(port)])

    assert exit_code == 3  # the damage is reported, and only reported
    assert damaged.exists()
    assert "[fail] database_integrity:" in capsys.readouterr().out


def test_the_size_budget_leaves_a_huge_database_with_only_its_header_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _database(tmp_path / "data" / ".thomas" / "big.sqlite3", damaged_body=True)
    assert boot_checks.database_state(db)[0] == "corrupt"  # the full check finds the damage
    assert boot_checks.run_offline_checks(tmp_path, memory_root=tmp_path / "mem")[1] == [db.resolve()]

    monkeypatch.setattr(boot_checks, "_QUICK_CHECK_MAX_BYTES", 1000)
    rows, damaged = boot_checks.run_offline_checks(tmp_path, memory_root=tmp_path / "mem")

    assert damaged == []  # too big to read in full while someone waits on a failed start
    assert boot_checks.database_state(db, full_check=False)[1].startswith("header is valid")


def test_the_total_budget_checks_the_first_databases_in_full_and_only_the_header_of_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _database(tmp_path / "data" / ".thomas" / "a.sqlite3", damaged_body=True)
    _database(tmp_path / "data" / ".thomas" / "b.sqlite3", damaged_body=True)
    monkeypatch.setattr(boot_checks, "_QUICK_CHECK_TOTAL_BYTES", first.stat().st_size + 10)

    _rows, damaged = boot_checks.run_offline_checks(tmp_path, memory_root=tmp_path / "mem")

    assert [path.name for path in damaged] == ["a.sqlite3"]
