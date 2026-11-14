"""Redesign Undo resolves every project path through the files slot and never leaves the project root."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from thomas.forge.anvil import forge_code_redesign_undo as undo
from thomas.tools import fs_scope


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "work"
    sibling = tmp_path / "work2"
    outside = tmp_path / "outside"
    for folder in (root, sibling, outside):
        folder.mkdir()
        (folder / "f.txt").write_text("x", encoding="utf-8")
    return {"root": root, "sibling": sibling, "outside": outside}


def test_ordinary_paths_inside_still_resolve(world) -> None:
    root = world["root"].resolve()
    assert undo._safe_path(world["root"], "f.txt") == root / "f.txt"
    assert undo._safe_path(world["root"], "new/dir/file.txt") == root / "new" / "dir" / "file.txt"
    assert undo._safe_path(world["root"], "a/../f.txt") == root / "f.txt"
    assert undo._safe_path(world["root"], "") == root


def test_dotdot_is_refused(world) -> None:
    for rel in ("..", "../outside/f.txt", "sub/../../outside/f.txt"):
        with pytest.raises(undo.RedesignUndoError, match="outside the selected project"):
            undo._safe_path(world["root"], rel)


def test_a_shared_prefix_sibling_is_refused(world) -> None:
    for rel in ("../work2/f.txt", str(world["sibling"] / "f.txt"), str(world["sibling"])):
        with pytest.raises(undo.RedesignUndoError):
            undo._safe_path(world["root"], rel)


def test_an_absolute_path_elsewhere_is_refused(world) -> None:
    with pytest.raises(undo.RedesignUndoError):
        undo._safe_path(world["root"], str(world["outside"] / "f.txt"))


@pytest.mark.skipif(sys.platform != "win32", reason="another drive and UNC names are Windows rules")
def test_another_drive_or_unc_name_is_refused(world) -> None:
    for rel in ("D:/elsewhere/f.txt", "D:f.txt", "//server/share/f.txt"):
        try:
            got = undo._safe_path(world["root"], rel)
        except undo.RedesignUndoError:
            continue
        # a leading-slash UNC form is read as a relative name under the root, which stays inside
        assert got.resolve().is_relative_to(world["root"].resolve()), rel


def test_a_symlinked_parent_out_of_the_root_is_refused(world) -> None:
    link = world["root"] / "link"
    try:
        link.symlink_to(world["outside"], target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this account cannot create a symlink: {exc}")
    with pytest.raises(undo.RedesignUndoError):
        undo._safe_path(world["root"], "link/f.txt")


def test_a_junction_parent_out_of_the_root_is_refused(world) -> None:
    if os.name != "nt":
        pytest.skip("junctions exist only on Windows")
    junction = world["root"] / "junction"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(world["outside"])],
        capture_output=True,
        text=True,
        check=False,
    )
    if made.returncode != 0 or not junction.exists():
        pytest.skip(f"could not create a junction: {made.stdout.strip()} {made.stderr.strip()}")
    with pytest.raises(undo.RedesignUndoError):
        undo._safe_path(world["root"], "junction/f.txt")


def test_a_leaf_link_is_kept_not_followed(world) -> None:
    link = world["root"] / "leaf"
    try:
        link.symlink_to(world["outside"] / "f.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this account cannot create a symlink: {exc}")
    got = undo._safe_path(world["root"], "leaf")
    assert got == world["root"].resolve() / "leaf"
    assert got.is_symlink()


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive paths are a Windows rule")
def test_case_changes_stay_inside_and_other_folders_do_not(world) -> None:
    swapped = Path(str(world["root"]).swapcase())
    assert undo._safe_path(swapped, "f.txt").name.lower() == "f.txt"
    with pytest.raises(undo.RedesignUndoError):
        undo._safe_path(world["root"], str(world["sibling"]).swapcase())


def test_the_path_goes_through_the_files_slot_at_call_time(world) -> None:
    asked: list[str] = []
    real = fs_scope.Scope.resolve

    def spy(self, rel):
        asked.append(rel)
        return real(self, rel)

    with patch.object(fs_scope.Scope, "resolve", spy):
        undo._safe_path(world["root"], "sub/f.txt")
    assert asked


def test_a_refusing_slot_stops_the_restore_path(world) -> None:
    def refuse(self, rel):
        raise ValueError("Path escapes sandbox")

    with patch.object(fs_scope.Scope, "resolve", refuse):
        with pytest.raises(undo.RedesignUndoError):
            undo._safe_path(world["root"], "f.txt")
