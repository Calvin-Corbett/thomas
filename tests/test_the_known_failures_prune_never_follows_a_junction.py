"""Known-failure cleanup must never reach through directory junctions."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from thomas.server import green_checkout
from thomas.server.precard import known


def _name(number: int) -> str:
    return f"{number:064x}"


def _record(folder: Path, number: int, age: float) -> Path:
    path = folder / f"{_name(number)}.json"
    path.write_text('["tests/test_x.py::test_one"]', encoding="utf-8")
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def _junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("directory junctions require Windows")
    try:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("directory junction creation is unavailable")
    assert link.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT


def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "green"
    root.mkdir()
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    return root


def test_old_record_outside_a_junctioned_known_folder_survives_without_is_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    old = _record(outside, 1, 40 * 86400)
    _junction(root / known.FOLDER, outside)
    monkeypatch.delattr(Path, "is_junction", raising=False)

    known.remember(_name(2), ["new"])

    assert old.exists()
    assert old.read_text(encoding="utf-8") == '["tests/test_x.py::test_one"]'


def test_all_records_outside_a_junctioned_known_folder_survive_without_is_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    records = [_record(outside, number, 200 - number) for number in range(201)]
    _junction(root / known.FOLDER, outside)
    monkeypatch.delattr(Path, "is_junction", raising=False)

    known.remember(_name(201), ["new"])

    assert all(path.exists() for path in records)
    assert len([path for path in records if path.exists()]) == 201


@pytest.mark.parametrize("without_method", [False, True], ids=["method-present", "method-removed"])
def test_old_record_shaped_junction_is_never_entered_or_removed_at_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, without_method: bool
) -> None:
    if not without_method and not hasattr(Path, "is_junction"):
        pytest.skip("this Python version has no junction method")
    root = _root(tmp_path, monkeypatch)
    folder = root / known.FOLDER
    folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    nested = _record(outside, 301, 40 * 86400)
    junction = folder / f"{_name(301)}.json"
    _junction(junction, outside)
    for number in range(201):
        record = _record(folder, number, -10 - number)
        assert junction.lstat().st_mtime < record.stat().st_mtime
    if without_method:
        monkeypatch.delattr(Path, "is_junction", raising=False)
    real_scandir = os.scandir
    entered: list[object] = []

    def track_scandir(path: object) -> object:
        if path in (junction, outside):
            entered.append(path)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", track_scandir)
    known.remember(_name(201), ["new"])

    assert not entered
    assert junction.exists()
    assert junction.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    assert nested.exists()
    assert len([path for path in folder.iterdir() if path.is_file()]) == 200
