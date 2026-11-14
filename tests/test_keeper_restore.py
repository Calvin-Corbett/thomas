"""Keeper capture v1 (design section 6, P0.3): a restore gives back the same bytes, into a new folder only, and
refuses a capture whose archive changed or whose paths would leave that folder."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile

import pytest
from scripts.keeper import keep as keep_mod
from scripts.keeper.capture import capture_tree
from scripts.keeper.keep import RestoreFailed, restore

# world is a pytest fixture, shared through keeper_support
from tests.keeper_support import fixture_git, git_binary, world, write


def test_restore_gives_back_identical_bytes_and_commits(world, tmp_path):
    original = {rel: (world.place / rel).read_bytes() for rel in ("a.txt", "new.txt")}
    result = capture_tree(world.place, world.settings(), world.main_git)
    dest = tmp_path / "drill"
    report = restore(world.keep, result["id"], dest, git_path=git_binary(), main_objects=world.main_git / "objects")
    assert report["ok"], report["problems"]
    for rel, data in original.items():
        assert (dest / "files" / rel).read_bytes() == data
    assert (dest / "base" / "a.txt").read_bytes() == b"alpha\n"
    assert (dest / "base" / "gone.txt").read_bytes() == b"bye\n"
    assert [r["ok"] for r in report["refs"]] == [True]
    restored = fixture_git(dest / "commits.git", "--git-dir=.", "show", "refs/keep/0:feature.txt")
    assert restored == "only in the clone's commit"


def test_restore_dry_run_writes_nothing(world, tmp_path):
    result = capture_tree(world.place, world.settings(), world.main_git)
    report = restore(world.keep, result["id"], tmp_path / "dry", dry_run=True)
    assert "files/a.txt" in report["would_write"] and not (tmp_path / "dry").exists()


def test_restore_refuses_a_folder_that_is_not_new_and_empty(world, tmp_path):
    result = capture_tree(world.place, world.settings(), world.main_git)
    write(tmp_path / "busy" / "x.txt", "already here")
    with pytest.raises(RestoreFailed, match="new, empty folder"):
        restore(world.keep, result["id"], tmp_path / "busy")
    assert (tmp_path / "busy" / "x.txt").read_text() == "already here"


def test_restore_detects_a_changed_archive(world, tmp_path):
    result = capture_tree(world.place, world.settings(), world.main_git)
    copy = tmp_path / "keep-copy"
    shutil.copytree(world.keep, copy)
    zpath = next(copy.rglob("*.zip"))
    data = bytearray(zpath.read_bytes())
    data[len(data) // 2] ^= 0xFF
    zpath.write_bytes(bytes(data))
    with pytest.raises(RestoreFailed, match="sha256"):
        restore(copy, result["id"], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_restore_refuses_a_path_that_leaves_the_folder(tmp_path):
    keep, cap_id = tmp_path / "keep", "cap-20261009T120000Z-0123abcd-beef"
    folder = keep / "captures" / "2026-10"
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / f"{cap_id}.zip", "w") as zipped:
        zipped.writestr("files/../../escaped.txt", b"out")
    sha = hashlib.sha256((folder / f"{cap_id}.zip").read_bytes()).hexdigest()
    manifest = {
        "format": keep_mod.FORMAT,
        "id": cap_id,
        "archive": {"name": f"{cap_id}.zip", "sha256": sha},
        "entries": [{"stored": "files/../../escaped.txt", "sha256": hashlib.sha256(b"out").hexdigest()}],
    }
    (folder / f"{cap_id}.json").write_text(json.dumps(manifest))
    with pytest.raises(RestoreFailed, match="unsafe path"):
        restore(keep, cap_id, tmp_path / "out" / "dest")
    assert not (tmp_path / "out").exists() and not (tmp_path / "escaped.txt").exists()
