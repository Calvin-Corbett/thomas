"""`bootdoctor check` fails a folder it cannot write to and a config it cannot read, and stays inside its limits.

Only "the state folder is a file" and "the config is not UTF-8" were covered. A folder that refuses the test write
and a config file that refuses to open are the other two faults the changelog names, and each must stay a [fail]
that names the path, because the exit code repair.cmd acts on comes from it. The scan limits and the console guard
belong here too: each can be broken without any other test noticing.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

import thomas.bootdoctor.__main__ as bd_main
from tests._bootdoctor_fakes import isolate_offline_checks
from thomas.bootdoctor.check_command import run_check
from thomas.core import boot_checks


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)


def _damaged(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a database at all" * 5)
    return path


def _refuse_the_probe_file(folder: Path) -> Path:
    """A real OSError from the test write: a folder already stands where the probe file would go."""
    folder.mkdir(parents=True, exist_ok=True)
    blocker = folder / f".bootdoctor_write_{os.getpid()}"
    blocker.mkdir()
    return blocker


def test_a_folder_that_refuses_the_test_write_fails_the_check_and_names_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "state"
    blocker = _refuse_the_probe_file(folder)

    check, status, detail = boot_checks.check_writable(folder)

    assert (check, status) == ("state_dir_writable", "fail")
    assert detail.startswith(f"{folder}: cannot write (")
    assert blocker.is_dir()  # the failed probe left nothing of its own behind


def test_a_state_folder_that_cannot_be_written_exits_one_with_the_folder_named(tmp_path: Path, capsys) -> None:
    _refuse_the_probe_file(tmp_path / "runtime")

    exit_code = bd_main.main(["check", "--root", str(tmp_path), "--port", "22127"])

    assert exit_code == 1
    assert f"[fail] state_dir_writable: {(tmp_path / 'runtime').resolve()}: cannot write (" in capsys.readouterr().out


def test_a_config_file_that_will_not_open_fails_the_check_and_names_the_file(tmp_path: Path) -> None:
    # A folder called thomas.toml exists, so it is not "absent", and opening it is refused by the operating system.
    config = tmp_path / "thomas.toml"
    config.mkdir()

    check, status, detail = boot_checks.check_config_file(config)

    assert (check, status) == ("config_file", "fail")
    assert detail.startswith(f"{config}: cannot be read (")


def test_a_config_file_that_will_not_open_exits_one(tmp_path: Path, capsys) -> None:
    (tmp_path / "thomas.toml").mkdir()

    assert bd_main.main(["check", "--root", str(tmp_path), "--port", "22127"]) == 1

    assert "[fail] config_file:" in capsys.readouterr().out


def test_the_scan_reaches_three_folders_below_the_state_folder_and_no_further(tmp_path: Path) -> None:
    mem = tmp_path / "mem"
    reached = _damaged(mem / ".thomas" / "a" / "b" / "c" / "deep.sqlite3")
    _damaged(mem / ".thomas" / "a" / "b" / "c" / "d" / "too_deep.sqlite3")

    _rows, damaged = boot_checks.run_offline_checks(tmp_path, memory_root=mem)

    assert damaged == [reached.resolve()]


def test_no_more_than_sixty_databases_are_checked_in_one_run(tmp_path: Path) -> None:
    mem = tmp_path / "mem" / ".thomas"
    mem.mkdir(parents=True)
    for number in range(65):
        (mem / f"db{number:02}.sqlite3").write_bytes(b"")

    rows, damaged = boot_checks.run_offline_checks(tmp_path, memory_root=tmp_path / "mem")

    assert damaged == []
    assert ("database_integrity", "ok", "60 database file(s) checked; none damaged") in rows


def test_a_failed_start_is_classified_by_the_last_fifty_lines_of_its_log() -> None:
    # The server names the error and then logs while it shuts down, so the cause is not the very last line.
    crash = "ModuleNotFoundError: No module named 'aiohttp'"

    def log_with(after: int) -> str:
        return "\n".join([crash, *(f"INFO: shutting down {n}" for n in range(after))])

    assert boot_checks.classify_startup_log(log_with(49)) == ["a Python package is missing (aiohttp)"]
    assert boot_checks.classify_startup_log(log_with(50)) == []


def test_a_console_that_cannot_print_a_path_still_gets_the_report(tmp_path: Path, monkeypatch) -> None:
    # A legacy code page raises on a character it cannot encode. The check prints paths, so it asks the console to
    # substitute instead of dying before it has said what is wrong.
    config = tmp_path / "thomas-é.toml"
    config.write_text("[server]\nport = 22127\n", encoding="utf-8")
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)

    exit_code = run_check(root=tmp_path, memory_root=tmp_path / "mem", config_path=str(config))
    console.flush()

    assert exit_code == 0
    assert b"thomas-?.toml parses" in raw.getvalue()
