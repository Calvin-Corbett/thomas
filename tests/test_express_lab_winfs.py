"""The Windows primitives under the lab fail loudly: no helper answers "no" when it could not look.

``is_reparse_point`` and ``file_attributes`` must raise on any failure other than "the path is not there", because a
check built on an answer of "no" that really meant "I could not look" would pass on a path it could not read. A
junction that cannot be made is a broken fixture, not a machine limit. The sparse giant is only written after four
checks (the volume reports sparse support, free space exceeds the logical size, a 16 MiB probe keeps its holes, and
the file itself keeps them), and the order matters: a dense 4 GiB file would fill the drive.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.express_winfs as winfs
from tests.express_pytest import skip_or_fail
from tests.express_winfs import (
    IS_WINDOWS,
    EnvironmentUnavailable,
    FixtureBroken,
    create_junction,
    file_attributes,
    is_reparse_point,
)

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="needs NTFS junctions, streams and sparse files")


def test_the_reparse_check_answers_no_only_for_a_path_that_is_not_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not is_reparse_point(tmp_path / "absent") and not is_reparse_point(tmp_path)

    def denied(path, *args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(os, "lstat", denied)
    with pytest.raises(PermissionError):
        is_reparse_point(tmp_path)
    with pytest.raises(PermissionError):
        file_attributes(tmp_path)


@windows_only
def test_a_junction_that_cannot_be_made_is_a_broken_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import _winapi

    def refuse(*_args):
        raise OSError("no junction for you")

    monkeypatch.setattr(_winapi, "CreateJunction", refuse)
    with pytest.raises(FixtureBroken, match="no junction"):
        create_junction(tmp_path / "link", tmp_path)


@windows_only
def test_the_sparse_giant_is_written_only_after_every_safety_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    giant, written = tmp_path / "giant.bin", []
    real_write = winfs._write_sparse
    monkeypatch.setattr(winfs, "_write_sparse", lambda path, size: written.append(path.name) or real_write(path, size))

    monkeypatch.setattr(winfs, "volume_supports_sparse", lambda folder: False)
    with pytest.raises(EnvironmentUnavailable, match="sparse"):
        winfs.create_sparse_giant(giant, 1 << 30)
    monkeypatch.setattr(winfs, "volume_supports_sparse", lambda folder: True)
    monkeypatch.setattr(winfs.shutil, "disk_usage", lambda folder: SimpleNamespace(free=1 << 20))
    with pytest.raises(EnvironmentUnavailable, match="free space"):
        winfs.create_sparse_giant(giant, 1 << 30)
    assert written == [] and not giant.exists()  # nothing at all was written yet

    monkeypatch.setattr(winfs.shutil, "disk_usage", lambda folder: SimpleNamespace(free=1 << 50))
    monkeypatch.setattr(winfs, "_holds_holes", lambda path: False)
    with pytest.raises(EnvironmentUnavailable, match="probe"):
        winfs.create_sparse_giant(giant, 1 << 30)
    assert written == [".sparse-probe"] and not giant.exists() and not (tmp_path / ".sparse-probe").exists()

    monkeypatch.setattr(
        winfs, "_holds_holes", lambda path: path.name == ".sparse-probe"
    )  # the probe passes, the file does not
    with pytest.raises(EnvironmentUnavailable, match="took real disk space"):
        winfs.create_sparse_giant(giant, 1 << 30)
    assert not giant.exists() and not (tmp_path / ".sparse-probe").exists()


@windows_only
def test_a_real_sparse_giant_keeps_its_holes(tmp_path: Path) -> None:
    giant = tmp_path / "giant.bin"
    try:
        winfs.create_sparse_giant(giant, 1 << 30)
    except EnvironmentUnavailable as exc:
        skip_or_fail(str(exc))
    assert giant.stat().st_size == 1 << 30 and winfs.allocated_size(giant) < 1 << 20


@windows_only
def test_listing_streams_answers_no_only_when_it_could_look(tmp_path: Path) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    assert winfs.alternate_streams(folder) == []  # a folder with no streams: git-style "I looked, nothing there"
    with pytest.raises(OSError):
        winfs.alternate_streams(tmp_path / "absent")  # a path it cannot look at is an error, never "no streams"
