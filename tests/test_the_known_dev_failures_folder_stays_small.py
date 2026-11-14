"""Dev-failure hints expire without changing what a check confirms."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from thomas.server import green_checkout
from thomas.server.precard import known


def _folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path)
    folder = tmp_path / known.FOLDER
    folder.mkdir()
    return folder


def _name(number: int) -> str:
    return f"{number:064x}"


def _record(folder: Path, number: int, age: float) -> Path:
    path = folder / f"{_name(number)}.json"
    path.write_text('["tests/test_x.py::test_one"]', encoding="utf-8")
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def test_write_removes_records_unused_for_30_days_but_not_recent_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch)
    old = _record(folder, 1, 31 * 86400)
    recent = _record(folder, 2, 29 * 86400)

    known.remember(_name(3), ["tests/test_x.py::test_new"])

    assert not old.exists()
    assert recent.exists()
    assert known.read(_name(3)) == frozenset({"tests/test_x.py::test_new"})


def test_write_keeps_only_200_records_with_the_most_recently_used_and_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch)
    for number in range(201):
        _record(folder, number, 201 - number)

    known.remember(_name(201), ["new"])

    remaining = {path.name for path in folder.iterdir()}
    assert len(remaining) == 200
    assert f"{_name(0)}.json" not in remaining
    assert f"{_name(1)}.json" not in remaining
    assert f"{_name(201)}.json" in remaining


def test_read_refreshes_an_old_record_before_the_next_write_prunes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch)
    old = _record(folder, 1, 31 * 86400)
    unused = _record(folder, 3, 31 * 86400)
    assert known.read(_name(1)) == frozenset({"tests/test_x.py::test_one"})

    known.remember(_name(2), ["new"])

    assert old.exists()
    assert not unused.exists()
    assert known.read(_name(1)) == frozenset({"tests/test_x.py::test_one"})


def test_prune_ignores_directories_and_other_names_and_cannot_change_a_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch)
    directory = folder / f"{_name(1)}.json"
    directory.mkdir()
    when = time.time() - 31 * 86400
    os.utime(directory, (when, when))
    foreign = folder / "other.json"
    foreign.write_text("not a record", encoding="utf-8")
    os.utime(foreign, (when, when))
    blocked = _record(folder, 2, 31 * 86400)
    removable = _record(folder, 4, 31 * 86400)
    real_unlink = Path.unlink

    def refuse_one(path: Path, *args: object, **kwargs: object) -> None:
        if path == blocked:
            raise PermissionError("file in use")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_one)
    known.remember(_name(3), ["new"])

    assert directory.is_dir()
    assert foreign.read_text(encoding="utf-8") == "not a record"
    assert blocked.exists()
    assert not removable.exists()
    assert known.read(_name(3)) == frozenset({"new"})


def test_a_recent_read_wins_over_older_records_at_the_200_record_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch)
    refreshed = _record(folder, 0, 2 * 86400)
    displaced = _record(folder, 1, 86400)
    for number in range(2, 201):
        _record(folder, number, 200 - number)

    assert known.read(_name(0)) == frozenset({"tests/test_x.py::test_one"})
    known.remember(_name(201), ["new"])

    assert refreshed.exists()
    assert not displaced.exists()
    assert len(list(folder.glob("*.json"))) == 200


def test_an_unlistable_folder_does_not_change_the_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = _folder(tmp_path, monkeypatch)
    old = _record(folder, 2, 31 * 86400)
    real_scandir = os.scandir
    attempted: list[object] = []

    def deny_folder(path: object) -> object:
        if path == folder:
            attempted.append(path)
            raise PermissionError("cannot list")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", deny_folder)
    known.remember(_name(3), ["new"])

    assert known.read(_name(3)) == frozenset({"new"})
    assert attempted
    assert old.exists()


def _junction(link: Path, destination: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("directory junctions require Windows")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(destination)], check=True, capture_output=True)


def test_a_record_shaped_junction_does_not_enter_its_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    nested = _record(outside, 8, 31 * 86400)
    link = folder / f"{_name(1)}.json"
    _junction(link, outside)
    old = _record(folder, 2, 31 * 86400)

    known.remember(_name(3), ["new"])

    assert not old.exists()
    assert link.is_junction()
    assert nested.exists()


def test_a_junction_as_the_known_folder_does_not_prune_its_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch)
    folder.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    old = _record(outside, 1, 31 * 86400)
    _junction(folder, outside)

    known.remember(_name(3), ["new"])

    assert folder.is_junction()
    assert old.exists()
    assert known.read(_name(3)) == frozenset({"new"})


def test_a_name_outside_the_known_folder_never_prunes_that_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch)
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    old = _record(sibling, 1, 31 * 86400)
    in_folder = _record(folder, 2, 31 * 86400)

    known.remember(f"../sibling/{_name(3)}", ["new"])

    assert old.exists()
    assert not in_folder.exists()
    assert known.read(f"../sibling/{_name(3)}") == frozenset({"new"})


def test_a_record_shaped_symlink_is_never_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = _folder(tmp_path, monkeypatch)
    outside = tmp_path / "outside.json"
    outside.write_text("outside", encoding="utf-8")
    link = folder / f"{_name(1)}.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks unavailable")
    old = _record(folder, 2, 31 * 86400)

    known.remember(_name(4), ["next"])

    assert not old.exists()
    assert link.is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside"


def test_old_abandoned_temporary_files_are_removed_but_recent_ones_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch)
    old = folder / ".known-abcd1234.tmp"
    recent = folder / ".known-efgh5678.tmp"
    foreign = folder / ".known-a space!.tmp"
    old.write_text("old", encoding="utf-8")
    recent.write_text("new", encoding="utf-8")
    foreign.write_text("not written by mkstemp", encoding="utf-8")
    when = time.time() - 3601
    os.utime(old, (when, when))
    os.utime(foreign, (when, when))

    known.remember(_name(1), ["new"])

    assert not old.exists()
    assert recent.exists()
    assert foreign.exists()
    assert known.read(_name(1)) == frozenset({"new"})
