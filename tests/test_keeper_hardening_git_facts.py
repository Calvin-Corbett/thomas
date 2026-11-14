"""Regression tests for the security review of keeper capture v1 (P0.3): a git fact that cannot be read.

One section per finding, named by its id; the other findings are in ``test_keeper_hardening*.py``. Each test fails on
the code the review read and passes on the fix.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.keeper import gitplace
from scripts.keeper.capture import capture_tree, main
from scripts.keeper.places import keeper_fs

# world is a pytest fixture, shared through keeper_support
from tests.keeper_support import _manifest, _refused, fixture_git, git_binary, world, write

# --- corrupt-or-busy-index-aborts-whole-capture -----------------------------------------------------------------


def test_a_corrupt_index_still_saves_every_readable_only_copy(world):
    write(world.place / "rescue-me.txt", "the sole copy of real work\n")
    write(world.place / ".git" / "index", os.urandom(512))
    result = capture_tree(world.place, world.settings(), world.main_git)
    manifest = _manifest(world, result)
    by_path = {h["path"]: h for h in manifest["holdings"]}
    assert by_path["rescue-me.txt"]["verdict"] == "ONLY_COPY" and by_path["new.txt"]["verdict"] == "ONLY_COPY"
    assert by_path["a.txt"]["status"] == "modified"  # still compared with HEAD
    assert "files/rescue-me.txt" in {e["stored"] for e in manifest["entries"]}
    assert _refused(manifest)["git:index"] == "unreadable" and manifest["index_read"] is False
    assert result["state_same"] is True


def test_the_command_line_saves_and_exits_zero_despite_a_corrupt_index(world, capsys):
    write(world.place / ".git" / "index", os.urandom(512))
    common = ["--keep", str(world.keep), "--work", str(world.work), "--git", git_binary(), "--min-free-gb", "0"]
    assert main(["tree", str(world.place), "--main", str(world.main_git), *common]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["only_copy"] == 2 and out["refused"] >= 1


class _Busy:
    """The real seam, except that every read of ``target`` is followed by someone writing to it: a busy index."""

    def __init__(self, target: Path) -> None:
        self.inner, self.target = keeper_fs(), target

    def hold_dir(self, path: Path):
        return self.inner.hold_dir(path)

    def read_regular(self, path: Path, limit: int) -> bytes:
        data = self.inner.read_regular(path, limit)
        if os.path.normcase(str(path)) == os.path.normcase(str(self.target)):
            with open(self.target, "ab") as handle:
                handle.write(b"\0")
        return data


def test_an_index_rewritten_while_read_is_saved_and_reported_as_changed(world):
    result = capture_tree(world.place, world.settings(fs=_Busy(world.place / ".git" / "index")), world.main_git)
    manifest = _manifest(world, result)
    assert {"new.txt", "a.txt"} <= {h["path"] for h in manifest["holdings"]}
    assert "changed_while_reading" in next(r["detail"] for r in manifest["refused"] if r["path"] == "git:index")
    assert result["state_same"] is False  # exit code 3: saved, but someone was working there


def test_an_unreadable_head_still_saves_the_files_and_the_commits(world):
    write(world.place / ".git" / "HEAD", "not a ref\n")
    result = capture_tree(world.place, world.settings(), world.main_git)
    manifest = _manifest(world, result)
    assert _refused(manifest)["git:HEAD"] == "unreadable" and manifest["base"] is None
    assert {"new.txt", "a.txt"} <= {h["path"] for h in manifest["holdings"]}
    assert world.place_commit in {r["sha"] for r in manifest["bundle"]["refs"]}  # refs/heads/feature still read


def test_unreadable_packed_refs_still_read_the_loose_refs(world, monkeypatch):
    fixture_git(world.place, "pack-refs", "--all")
    write(world.place / "later.txt", "committed after the refs were packed\n")
    fixture_git(world.place, "add", "later.txt")
    fixture_git(world.place, "commit", "-q", "-m", "later")
    later = fixture_git(world.place, "rev-parse", "HEAD")
    monkeypatch.setattr(gitplace, "PACKED_REFS_LIMIT", 16)
    manifest = _manifest(world, capture_tree(world.place, world.settings(), world.main_git))
    assert _refused(manifest)["git:packed-refs"] == "unreadable"
    assert manifest["base"] == later and later in {r["sha"] for r in manifest["bundle"]["refs"]}
