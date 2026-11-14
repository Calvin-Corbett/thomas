"""`python -m thomas.bootdoctor check` and the offline checks under it (thomas/core/boot_checks.py)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import thomas.bootdoctor.__main__ as bd_main
from tests._bootdoctor_fakes import isolate_offline_checks
from thomas.core import boot_checks


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)


def _good_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("create table t (x)")
    con.executemany("insert into t values (?)", [(n,) for n in range(2000)])
    con.commit()
    con.close()


def test_a_config_file_that_will_not_parse_is_named_with_its_line(tmp_path: Path) -> None:
    bad = tmp_path / "thomas.toml"
    bad.write_text("[server\nport = = 1\n", encoding="utf-8")

    check, status, detail = boot_checks.check_config_file(bad)

    assert (check, status) == ("config_file", "fail")
    assert detail.startswith(str(bad))
    assert "line 1" in detail


def test_a_config_file_that_is_not_text_is_named(tmp_path: Path) -> None:
    bad = tmp_path / "thomas.toml"
    bad.write_bytes(b"\xff\xfe\x00 not utf-8")

    _check, status, detail = boot_checks.check_config_file(bad)

    assert status == "fail"
    assert str(bad) in detail


def test_a_good_or_missing_config_file_is_fine(tmp_path: Path) -> None:
    good = tmp_path / "thomas.toml"
    good.write_text("[server]\nport = 22058\n", encoding="utf-8")

    assert boot_checks.check_config_file(good)[1] == "ok"
    assert boot_checks.check_config_file(tmp_path / "absent.toml")[1] == "ok"


def test_database_state_tells_damage_from_health(tmp_path: Path) -> None:
    good = tmp_path / "good.sqlite3"
    _good_database(good)
    text = tmp_path / "text.sqlite3"
    text.write_bytes(b"this was never a database" * 10)
    cut = tmp_path / "cut.sqlite3"
    cut.write_bytes(good.read_bytes()[: 4096 + 100])
    empty = tmp_path / "empty.sqlite3"
    empty.write_bytes(b"")

    assert boot_checks.database_state(good)[0] == "ok"
    assert boot_checks.database_state(empty)[0] == "ok"
    assert boot_checks.database_state(text) == ("corrupt", "file is not a database")
    assert boot_checks.database_state(cut)[0] == "corrupt"


def test_a_database_given_by_a_relative_path_is_still_checked(tmp_path: Path) -> None:
    # A relative path cannot be written as a file:// URI, which the read-only open needs.
    _good_database(tmp_path / "rel.sqlite3")

    assert boot_checks.database_state(Path("rel.sqlite3")) == ("ok", "integrity ok")


def test_a_dot_db_file_that_is_not_sqlite_is_a_warning_and_never_moved(tmp_path: Path, capsys) -> None:
    # ".db" is used by other programs too, so it must not be reported as damage or offered for moving.
    other = tmp_path / "data" / "cache.db"
    other.parent.mkdir()
    other.write_bytes(b"some other program's format" * 4)

    assert boot_checks.database_state(other) == ("suspect", "not a SQLite file")
    assert _check(tmp_path) == 0
    assert _check(tmp_path, "--quarantine") == 0

    assert other.exists()
    assert "[warn] database_integrity:" in capsys.readouterr().out


def test_a_state_folder_that_is_a_file_fails_the_writable_check(tmp_path: Path) -> None:
    blocked = tmp_path / "state"
    blocked.write_text("in the way", encoding="utf-8")

    _check, status, detail = boot_checks.check_writable(blocked / "sub")

    assert status == "fail"
    assert "is a file, not a folder" in detail


def test_quarantine_renames_a_damaged_database_and_keeps_its_bytes(tmp_path: Path) -> None:
    damaged = tmp_path / "runs.sqlite3"
    damaged.write_bytes(b"damaged bytes")
    wal = tmp_path / "runs.sqlite3-wal"
    wal.write_bytes(b"wal bytes")

    notes = boot_checks.quarantine_corrupt([damaged])

    assert not damaged.exists()
    assert not wal.exists()
    moved = list(tmp_path.glob("runs.sqlite3.corrupt-*"))
    assert [p.name for p in moved if not p.name.endswith("-wal")] != []
    assert any(p.read_bytes() == b"damaged bytes" for p in moved)
    assert any(p.read_bytes() == b"wal bytes" for p in moved)
    assert any("moved" in note for note in notes)


def test_quarantine_moves_every_sidecar_file_with_its_database(tmp_path: Path) -> None:
    damaged = tmp_path / "runs.sqlite3"
    damaged.write_bytes(b"damaged bytes")
    sidecars = ("-wal", "-shm", "-journal")
    for suffix in sidecars:
        (tmp_path / f"runs.sqlite3{suffix}").write_bytes(suffix.encode())

    boot_checks.quarantine_corrupt([damaged])

    # A hot journal left beside the fresh database could be replayed into it.
    assert [p.name for p in tmp_path.glob("runs.sqlite3*") if ".corrupt-" not in p.name] == []
    for suffix in sidecars:
        (moved,) = tmp_path.glob(f"runs.sqlite3.corrupt-*{suffix}")
        assert moved.read_bytes() == suffix.encode()


def test_a_database_under_the_install_runtime_folder_is_checked(tmp_path: Path) -> None:
    # An install with no THOMAS_MEMORY_ROOT keeps runtime/.thomas/*.sqlite3 next to the code, not in the data dir.
    install = tmp_path / "install"
    damaged = install / "runtime" / ".thomas" / "runs.sqlite3"
    damaged.parent.mkdir(parents=True)
    damaged.write_bytes(b"not a database at all" * 5)

    _rows, corrupt = boot_checks.run_offline_checks(install, memory_root=tmp_path / "mem")

    assert corrupt == [damaged.resolve()]


def test_the_config_file_checked_is_the_one_thomas_would_read(tmp_path: Path, monkeypatch) -> None:
    default, from_env, explicit = tmp_path / "thomas.toml", tmp_path / "env.toml", tmp_path / "explicit.toml"

    assert boot_checks.config_file_path(tmp_path) == default.resolve()
    monkeypatch.setenv("THOMAS_CONFIG", str(from_env))
    assert boot_checks.config_file_path(tmp_path) == from_env.resolve()
    assert boot_checks.config_file_path(tmp_path, explicit) == explicit.resolve()


def test_check_tests_the_config_it_was_told_to_and_not_the_one_beside_the_root(tmp_path: Path, capsys) -> None:
    (tmp_path / "thomas.toml").write_text("[server]\nport = 22058\n", encoding="utf-8")
    bad = tmp_path / "elsewhere.toml"
    bad.write_text("[server\n", encoding="utf-8")

    assert _check(tmp_path, "--config", str(bad)) == 1

    out = capsys.readouterr().out
    assert f"[fail] config_file: {bad.resolve()}" in out


def test_a_config_that_will_not_load_is_named_in_the_warning(tmp_path: Path) -> None:
    bad = tmp_path / "elsewhere.toml"
    bad.write_text("[server\n", encoding="utf-8")

    _config, warning = bd_main._load_config_safe(str(bad))

    assert str(bad.resolve()) in warning
    assert "using defaults" in warning


def test_known_failure_signatures_are_named() -> None:
    cases = {
        "sqlite3.DatabaseError: file is not a database": "a Thomas database file is damaged",
        "tomllib.TOMLDecodeError: Invalid statement (at line 1, column 1)": "thomas.toml does not parse",
        "PermissionError: [WinError 5] Access is denied": "a file or folder Thomas needs is not writable",
        "OSError: [WinError 10048] Only one usage of each socket address": "the port is already taken",
        "OSError: [Errno 98] error while attempting to bind on address": "the port is already taken",
        "ModuleNotFoundError: No module named 'aiohttp'": "a Python package is missing (aiohttp)",
    }
    for log, cause in cases.items():
        assert any(cause in found for found in boot_checks.classify_startup_log(log)), log
    assert boot_checks.classify_startup_log("INFO: Thomas starting") == []
    # "Errno 98" is not a prefix match: Errno 980 is some other error.
    assert boot_checks.classify_startup_log("OSError: [Errno 980] something else") == []


def test_a_refused_bind_is_a_blocked_port_and_not_an_unwritable_folder() -> None:
    # WinError 10013 (a reserved port range, or a program refusing the bind) also raises PermissionError.
    forbidden = "a socket in a way forbidden by its access permissions"
    plain = f"PermissionError: [WinError 10013] An attempt was made to access {forbidden}"
    asyncio_wrapped = (
        "PermissionError: [Errno 13] error while attempting to bind on address ('127.0.0.1', 22058): "
        f"an attempt was made to access {forbidden}"
    )
    for log in (plain, asyncio_wrapped):
        assert boot_checks.classify_startup_log(log) == [
            "the port is blocked by Windows (a reserved port range or a permissions rule)"
        ], log
    taken = "OSError: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 22058): only one usage"
    assert boot_checks.classify_startup_log(taken) == ["the port is already taken by another program"]


def test_only_the_end_of_a_log_is_classified() -> None:
    # A PermissionError the server handled and carried on past, long before it died of something else.
    early = "PermissionError: [WinError 5] Access is denied: 'C:/cache/lock'  (retried)"
    filler = [f"INFO: still starting {n}" for n in range(80)]
    crash = "ModuleNotFoundError: No module named 'aiohttp'"

    found = boot_checks.classify_startup_log("\n".join([early, *filler, crash]))

    assert found == ["a Python package is missing (aiohttp)"]
    # The same error inside the last lines is still named.
    assert any("not writable" in cause for cause in boot_checks.classify_startup_log("\n".join([*filler, early])))


def test_log_tail_keeps_the_last_lines_only() -> None:
    text = "\n".join(f"line {n}" for n in range(40)) + "\n\n"

    tail = boot_checks.log_tail(text, lines=3)

    assert tail == ["line 37", "line 38", "line 39"]


def _check(tmp_path: Path, *extra: str) -> int:
    return bd_main.main(["check", "--root", str(tmp_path), "--port", "22057", *extra])


def test_check_exits_zero_when_nothing_is_wrong(tmp_path: Path, capsys) -> None:
    _good_database(tmp_path / "data" / ".thomas" / "runs.sqlite3")

    assert _check(tmp_path) == 0

    assert "[ok] database_integrity: 1 database file(s) checked" in capsys.readouterr().out


def test_check_exits_one_for_a_config_a_repair_cannot_move_aside(tmp_path: Path, capsys) -> None:
    (tmp_path / "thomas.toml").write_text("[server\n", encoding="utf-8")

    assert _check(tmp_path) == 1

    assert "[fail] config_file:" in capsys.readouterr().out


def test_check_exits_three_for_a_damaged_database_and_quarantine_clears_it(tmp_path: Path, capsys) -> None:
    damaged = tmp_path / "data" / ".thomas" / "runs.sqlite3"
    damaged.parent.mkdir(parents=True)
    damaged.write_bytes(b"not a database at all" * 5)

    assert _check(tmp_path) == 3
    assert damaged.exists()  # a plain check only reads

    assert _check(tmp_path, "--quarantine") == 0

    assert not damaged.exists()
    assert len(list(damaged.parent.glob("runs.sqlite3.corrupt-*"))) == 1
    assert "checked again after the move" in capsys.readouterr().out
