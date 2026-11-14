"""Regression tests for the security review of keeper capture v1 (P0.3): how a place is read.

One section per finding, named by its id; the other findings are in ``test_keeper_hardening*.py``. Each test fails on
the code the review read and passes on the fix.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from scripts.cage.referee.gitenv import GitRunner
from scripts.keeper import capture_tree as capture_tree_mod
from scripts.keeper import gitplace
from scripts.keeper.capture import capture_tree
from scripts.keeper.gitplace import Unreadable
from scripts.keeper.places import keeper_fs

from tests.express_winfs import IS_WINDOWS, create_junction

# world is a pytest fixture, shared through keeper_support
from tests.keeper_support import _manifest, _refused, keep_files, world, write

# --- check-ignore-chdir-into-untrusted-place ---------------------------------------------------------------------


def test_no_git_call_names_the_place_or_runs_from_it(world, monkeypatch):
    calls: list[tuple[list[str], str]] = []
    real_spawn = GitRunner._spawn

    def recording(self, args, extra, data, index, check, repo):
        calls.append(([*extra, *args], str(self.cwd)))
        return real_spawn(self, args, extra, data, index, check, repo)

    monkeypatch.setattr(GitRunner, "_spawn", recording)
    result = capture_tree(world.place, world.settings(), world.main_git)
    place = os.path.normcase(str(world.place))
    forms = {place, place.replace("\\", "/")}
    assert any("check-ignore" in args for args, _ in calls)
    for args, cwd in calls:
        assert not any(form in os.path.normcase(a) for a in args for form in forms), args
        assert not os.path.normcase(cwd).startswith(place)
    assert {h["path"] for h in _manifest(world, result)["holdings"]} == {"a.txt", "new.txt", "gone.txt"}


def test_ignore_rules_at_every_level_still_hold_through_the_shadow(world):
    write(world.place / "sub" / ".gitignore", "*.tmp\n!keep.tmp\ncache/\n")
    for rel in ("sub/a.tmp", "sub/keep.tmp", "sub/cache/x.txt", "sub/other/cache", "sub/deeper/b.tmp", "c.tmp"):
        write(world.place / rel, f"{rel}\n")
    manifest = _manifest(world, capture_tree(world.place, world.settings(), world.main_git))
    held = {h["path"] for h in manifest["holdings"]}
    assert {"sub/.gitignore", "sub/keep.tmp", "sub/other/cache", "c.tmp"} <= held
    assert not held & {"sub/a.tmp", "sub/cache/x.txt", "sub/deeper/b.tmp", "debug.log", "build/out.bin"}


def test_a_hard_linked_gitignore_is_not_read_through(world):
    write(world.root / "Documents" / "rules", "*.dat\n")
    (world.place / "sub2").mkdir()
    os.link(world.root / "Documents" / "rules", world.place / "sub2" / ".gitignore")
    write(world.place / "sub2" / "x.dat", "saved, because the linked rules are not used\n")
    manifest = _manifest(world, capture_tree(world.place, world.settings(), world.main_git))
    assert "sub2/x.dat" in {h["path"] for h in manifest["holdings"]}
    assert _refused(manifest)["sub2/.gitignore"] == "hard_linked"


# --- place-root-reparse-not-checked-before-git-runs --------------------------------------------------------------


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions are Windows behaviour")
def test_a_place_that_is_itself_a_junction_is_refused_before_its_git_folder_is_read(world, monkeypatch):
    linked = world.root / "linked-place"
    create_junction(linked, world.place)

    def never(*_a, **_k):
        raise AssertionError("the place's .git was read through a junction")

    monkeypatch.setattr(capture_tree_mod, "locate", never)
    with pytest.raises(Unreadable, match="not a plain folder"):
        capture_tree(linked, world.settings(), world.main_git)
    assert keep_files(world.keep) == []


# --- read-stable-aba-with-mtime-reset ----------------------------------------------------------------------------


class _Swapped:
    """The real seam, except that the capture's own read of ``target`` sees other bytes of the same length: a file
    swapped while it was read and put back, with its size and write time restored, before the after-state."""

    def __init__(self, target: Path) -> None:
        self.inner, self.target, self.reads = keeper_fs(), target, 0

    def hold_dir(self, path: Path):
        return self.inner.hold_dir(path)

    def read_regular(self, path: Path, limit: int) -> bytes:
        data = self.inner.read_regular(path, limit)
        if os.path.normcase(str(path)) == os.path.normcase(str(self.target)):
            self.reads += 1
            if self.reads == 2:  # the before-state read first; this is the capture's read
                return bytes(b ^ 0x01 for b in data)
        return data


def test_a_file_swapped_and_restored_during_the_read_reads_changed(world):
    swapped = _Swapped(world.place / "new.txt")
    result = capture_tree(world.place, world.settings(fs=swapped), world.main_git)
    manifest = _manifest(world, result)
    assert swapped.reads == 3  # before-state, capture, after-state
    assert result["state_same"] is False
    assert any("captured: new.txt" in line for line in manifest["state"]["changes"])


def test_an_untouched_capture_still_reads_the_same(world):
    result = capture_tree(world.place, world.settings(), world.main_git)
    assert result["state_same"] is True and _manifest(world, result)["state"]["changes"] == []


def test_the_work_folder_is_left_empty_when_a_capture_stops_with_its_archive_open(world, monkeypatch):
    def broken(*_a, **_k):
        raise gitplace.GitFailed("git cat-file failed: simulated")

    monkeypatch.setattr(capture_tree_mod, "blobs_in_order", broken)
    with pytest.raises(gitplace.GitFailed):
        capture_tree(world.place, world.settings(), world.main_git)
    assert list(world.work.iterdir()) == []  # the open zip was closed first, so its folder could be removed
