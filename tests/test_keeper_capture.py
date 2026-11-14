"""Keeper capture v1 (design section 6, P0.3): what a capture saves, and that the keep is only ever added to.

A restore giving back the same bytes is in ``test_keeper_restore.py``; a green captured through the caged server's
file route is in ``test_keeper_green.py``."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from scripts.keeper import capture as capture_mod
from scripts.keeper import capture_steps
from scripts.keeper import capture_tree as capture_tree_mod
from scripts.keeper import keep as keep_mod
from scripts.keeper.capture import CaptureRefused, capture_folder, capture_tree, main
from scripts.keeper.keep import restore
from scripts.keeper.places import compare_states, place_state

# world is a pytest fixture, shared through keeper_support
from tests.keeper_support import _manifest, fixture_git, git_binary, keep_files, world, write


def test_tree_capture_saves_what_only_this_place_holds(world):
    result = capture_tree(world.place, world.settings(label="fixture clone"), world.main_git)
    manifest = _manifest(world, result)
    by_path = {h["path"]: h for h in manifest["holdings"]}
    assert set(by_path) == {"a.txt", "new.txt", "gone.txt"}
    assert by_path["a.txt"]["status"] == "modified" and by_path["a.txt"]["verdict"] == "ONLY_COPY"
    assert by_path["new.txt"]["status"] == "new" and by_path["new.txt"]["verdict"] == "ONLY_COPY"
    assert by_path["gone.txt"]["status"] == "deleted" and by_path["gone.txt"]["verdict"] == "DELETE_PENDING"
    assert manifest["churn"] == ["crlf.txt"]  # line endings only: listed, not stored
    stored = {e["stored"] for e in manifest["entries"]}
    assert "files/debug.log" not in stored and not any(s.startswith("files/build/") for s in stored)
    assert {"files/a.txt", "files/new.txt", "base/a.txt", "base/gone.txt"} <= stored
    assert manifest["dev"] == world.dev and manifest["base"] == world.place_commit
    assert [r["sha"] for r in manifest["bundle"]["refs"]] == [world.place_commit]
    assert manifest["bundle"]["prerequisites"] == [world.dev]
    assert [c["subject"] for c in manifest["commits"]] == ["feature commit the main repo has never seen"]
    assert manifest["state"]["same"] is True and result["state_same"] is True
    assert sorted(p.name for p in keep_files(world.keep)) == sorted(
        f"{result['id']}.{e}" for e in ("json", "zip", "bundle")
    )


def test_a_sparse_checkout_entry_is_not_a_deletion_and_its_ignore_rules_still_hold(world):
    fixture_git(world.place, "update-index", "--skip-worktree", "b/c.py", ".gitignore")
    (world.place / "b" / "c.py").unlink()
    (world.place / ".gitignore").unlink()  # git reads a sparse .gitignore from the index; so does the keeper
    manifest = _manifest(world, capture_tree(world.place, world.settings(), world.main_git))
    assert {h["path"] for h in manifest["holdings"]} == {"a.txt", "new.txt", "gone.txt"}
    assert manifest["skip_worktree"] == 2


def test_keep_is_only_ever_added_to(world, monkeypatch):
    """No rename, replace or move anywhere in a capture; a taken name is never overwritten, a new id is chosen."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the keeper renamed or moved a file")

    for owner, name in ((os, "replace"), (os, "rename"), (shutil, "move"), (Path, "rename"), (Path, "replace")):
        monkeypatch.setattr(owner, name, forbidden)
    first = capture_tree(world.place, world.settings(), world.main_git)
    before = {p: p.read_bytes() for p in keep_files(world.keep)}
    ids = iter([first["id"], first["id"].rsplit("-", 1)[0] + "-0000"])
    monkeypatch.setattr(capture_steps, "new_capture_id", lambda *_a: next(ids))
    second = capture_tree(world.place, world.settings(), world.main_git)
    assert second["id"] != first["id"]
    assert all(p.read_bytes() == data for p, data in before.items())  # nothing already in the keep changed
    assert len(keep_files(world.keep)) == 6


def test_write_new_refuses_an_existing_name(tmp_path):
    write(tmp_path / "taken.json", "first")
    with pytest.raises(FileExistsError):
        keep_mod.write_new(tmp_path / "taken.json", b"second")
    assert (tmp_path / "taken.json").read_text() == "first"


def test_size_cap_refuses_before_anything_reaches_the_keep(world):
    with pytest.raises(CaptureRefused, match="cap"):
        capture_tree(world.place, world.settings(cap_bytes=10), world.main_git)
    assert keep_files(world.keep) == []
    assert list(world.work.iterdir()) == []  # the private working copy is cleaned up too


def test_capture_refuses_a_keep_that_does_not_exist(world):
    settings = world.settings()
    settings.keep = world.root / "no-keep"
    with pytest.raises(CaptureRefused, match="does not exist"):
        capture_tree(world.place, settings, world.main_git)
    assert not settings.keep.exists()


def test_capture_refuses_to_write_inside_the_place(world):
    settings = world.settings()
    settings.work = world.place / "scratch"
    with pytest.raises(CaptureRefused, match="never go there"):
        capture_tree(world.place, settings, world.main_git)
    assert not (world.place / "scratch").exists()


def test_folder_capture_round_trip_and_deterministic_archive(world, tmp_path):
    folder = world.root / "scratchpad"
    write(folder / "notes" / "plan.md", "# plan\r\nkeep me\r\n")
    write(folder / "broken" / ".git" / "objects" / "ab" / "cdef", b"\x78\x01raw object bytes")
    write(folder / "__pycache__" / "x.pyc", b"cache")
    write(folder / "empty.txt", b"")
    write(folder / "copy-of-a.txt", "alpha\n")  # the same bytes as dev's a.txt
    first = capture_folder(folder, world.settings(), world.main_git)
    second = capture_folder(folder, world.settings(), world.main_git)
    m1, m2 = _manifest(world, first), _manifest(world, second)
    rels = ("notes/plan.md", "broken/.git/objects/ab/cdef", "empty.txt", "copy-of-a.txt")
    assert {h["path"] for h in m1["holdings"]} == set(rels)
    assert m1["excluded"] == ["__pycache__"] and m1["archive"]["sha256"] == m2["archive"]["sha256"]
    verdicts = {h["path"]: h["verdict"] for h in m1["holdings"]}
    assert verdicts["copy-of-a.txt"] == "IN_GIT" and verdicts["notes/plan.md"] == "ONLY_COPY"
    report = restore(world.keep, first["id"], tmp_path / "back")
    assert report["ok"]
    for rel in rels:
        assert (tmp_path / "back" / "files" / rel).read_bytes() == (folder / rel).read_bytes()


def test_place_state_sees_any_change_and_nothing_else(world):
    first, again = place_state(world.place), place_state(world.place)
    assert first["digest"] == again["digest"] and compare_states(first, again) == []
    write(world.place / "new.txt", "edited by someone working here\n")
    changed = place_state(world.place)
    assert [ln.split(" ")[0:2] for ln in compare_states(first, changed)] == [["changed:", "new.txt"]]


def test_capture_reports_a_place_that_changed_while_it_was_read(world, monkeypatch):
    real = capture_mod.place_state
    calls = []

    def state_then_edit(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:  # the after-state: someone saved a file during the capture
            write(world.place / "new.txt", "saved during the capture\n")
        return real(*args, **kwargs)

    monkeypatch.setattr(capture_tree_mod, "place_state", state_then_edit)  # the before-state
    monkeypatch.setattr(capture_steps, "place_state", state_then_edit)  # the after-state, in _finish
    result = capture_tree(world.place, world.settings(), world.main_git)
    manifest = _manifest(world, result)
    assert result["state_same"] is False and any("new.txt" in ln for ln in manifest["state"]["changes"])


def test_linked_worktree_is_read_through_its_registration(world):
    wt = world.root / "wt"
    fixture_git(world.main, "worktree", "add", "-q", "-b", "wtb", str(wt))
    write(wt / "a.txt", "alpha\nedited in the worktree\n")
    result = capture_tree(wt, world.settings(), world.main_git)
    manifest = _manifest(world, result)
    assert [h["path"] for h in manifest["holdings"]] == ["a.txt"] and manifest["linked"] is True
    assert manifest["bundle"] is None  # wtb is dev: no commit dev lacks
    registered = world.main_git / "worktrees" / "wt"
    assert set(manifest["state"]["places"]) == {str(wt), str(registered)} and manifest["state"]["same"] is True


def test_command_line_capture_and_restore(world, tmp_path, capsys):
    common = ["--keep", str(world.keep), "--work", str(world.work), "--git", git_binary(), "--min-free-gb", "0"]
    state_dir = tmp_path / "states"
    code = main(["tree", str(world.place), "--main", str(world.main_git), *common, "--state-dir", str(state_dir)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["only_copy"] == 2 and out["commits"] == 1
    assert sorted(p.name.split(".", 1)[1] for p in state_dir.iterdir()) == ["0.after.json", "0.before.json"]
    dest = tmp_path / "cli-restore"
    code = main(["restore", out["id"], str(dest), *common, "--main-objects", str(world.main_git / "objects")])
    assert code == 0 and json.loads(capsys.readouterr().out)["ok"] is True
    before, after = sorted(state_dir.iterdir())[1], sorted(state_dir.iterdir())[0]
    assert main(["compare", str(before), str(after)]) == 0
    capsys.readouterr()
    assert main(["size", "--keep", str(world.keep)]) == 0
    size = json.loads(capsys.readouterr().out)
    assert size["files"] == 3 and size["bytes"] == sum(p.stat().st_size for p in keep_files(world.keep))
