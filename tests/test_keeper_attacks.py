"""Reading a place without trusting it (design section 3): nothing a place plants can run, and no link is followed.

Each planted command writes a marker file when it runs. A canary first runs ordinary git in the planted place and
shows that the plants are live (at least one marker appears); the keeper then captures, records state and restores,
and no marker may appear.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest
from scripts.cage.referee.nofollow import UnsafeEntry
from scripts.keeper.capture import capture_folder, capture_tree
from scripts.keeper.gitplace import Unreadable
from scripts.keeper.keep import load_manifest, restore
from scripts.keeper.places import keeper_fs, place_state, read_stable

from tests.express_winfs import IS_WINDOWS, EnvironmentUnavailable, create_junction, create_symlink
from tests.keeper_support import build_world, fixture_git, git_binary, remove_tree, write

HOOKS = ("pre-commit", "post-checkout", "post-index-change", "reference-transaction", "pre-auto-gc", "post-merge")


@pytest.fixture
def world(tmp_path):
    w = build_world(tmp_path / "w")
    yield w
    remove_tree(tmp_path / "w")


def _marker(markers: Path, name: str) -> str:
    return f"echo ran > '{(markers / name).as_posix()}'"


def _replace_head(place: Path) -> None:
    """A ``refs/replace`` object that would make HEAD's a.txt read "REPLACED" to a git that honours it."""
    blob = fixture_git(place, "hash-object", "-w", "--stdin", data=b"REPLACED\n")
    tree = fixture_git(place, "mktree", data=f"100644 blob {blob}\ta.txt\n".encode())
    fake = fixture_git(place, "commit-tree", tree, "-m", "replacement")
    fixture_git(place, "replace", fixture_git(place, "rev-parse", "HEAD"), fake)


def plant(world) -> Path:
    """Arm the place: config commands, an include, attributes, two hook folders, a replace ref, three links."""
    place, markers = world.place, world.root / "markers"
    markers.mkdir()
    _replace_head(place)
    evil_hooks = world.root / "evil-hooks"
    for folder, tag in ((evil_hooks, "hookspath"), (place / ".git" / "hooks", "dothooks")):
        for name in HOOKS:
            write(folder / name, f"#!/bin/sh\n{_marker(markers, f'{tag}-{name}')}\n")
    write(world.root / "evil.inc", f"[core]\n\tfsmonitor = {_marker(markers, 'include')}\n")
    commands = {
        "core": {
            "fsmonitor": "fsmonitor",
            "sshCommand": "ssh",
            "pager": "pager",
            "editor": "editor",
            "askPass": "askpass",
        },
        'filter "x"': {"clean": "clean", "smudge": "smudge", "process": "process"},
        "diff": {"external": "diffext"},
        'diff "x"': {"textconv": "textconv"},
        'merge "x"': {"driver": "mergedriver"},
        "gpg": {"program": "gpg"},
        "uploadpack": {"packObjectsHook": "packhook"},
    }
    config = [f"[{section}]\n" + "".join(f"\t{k} = {_marker(markers, v)}\n" for k, v in keys.items()) for section, keys
              in commands.items()]  # fmt: skip
    config.append(f"[core]\n\thooksPath = {evil_hooks.as_posix()}\n")
    config.append("[credential]\n\thelper = !" + _marker(markers, "credential") + "\n")
    config.append(f"[include]\n\tpath = {(world.root / 'evil.inc').as_posix()}\n")
    with open(place / ".git" / "config", "a", encoding="utf-8") as handle:
        handle.write("".join(config))
    write(place / ".gitattributes", "* filter=x diff=x merge=x\n")
    write(place / ".git" / "info" / "attributes", "* filter=x diff=x merge=x\n")
    write(world.root / "Documents" / "secret2.txt", world.secret + b"-hard")
    create_junction(place / "docs-link", world.root / "Documents")
    os.link(world.root / "Documents" / "secret2.txt", place / "hard.txt")
    try:
        create_symlink(place / "sym.txt", world.root / "Documents" / "secret.txt")
    except EnvironmentUnavailable:
        pass  # no symlink privilege here: the junction and the hard link still stand
    return markers


def _clear(markers: Path) -> None:
    for marker in markers.iterdir():
        marker.unlink()


def _everything_written(world, result, *extra: Path) -> bytes:
    """Every byte the keeper produced for this capture, archive members decompressed."""
    path, _ = load_manifest(world.keep, result["id"])
    out = [p.read_bytes() for p in path.parent.iterdir()]
    for zpath in path.parent.glob("*.zip"):
        with zipfile.ZipFile(zpath) as zipped:
            out += [zipped.read(n) for n in zipped.namelist()]
    for folder in extra:
        out += [p.read_bytes() for p in folder.rglob("*") if p.is_file()]
    return b"\n".join(out)


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions and the real no-follow seam are Windows behaviour")
def test_keeper_never_runs_a_place_config(world, tmp_path):
    markers = plant(world)
    fixture_git(world.place, "status", check=False)  # the canary: ordinary git in the armed place
    fired = sorted(p.name for p in markers.iterdir())
    assert fired, "the plants did not fire under ordinary git, so this test would prove nothing"
    _clear(markers)

    result = capture_tree(world.place, world.settings(), world.main_git)
    state = place_state(world.place)
    dest = tmp_path / "restored"
    report = restore(world.keep, result["id"], dest, git_path=git_binary(), main_objects=world.main_git / "objects")

    assert sorted(p.name for p in markers.iterdir()) == []
    manifest = load_manifest(world.keep, result["id"])[1]
    refused = {r["path"]: r["code"] for r in manifest["refused"]}
    assert refused["docs-link"] == "reparse_point" and refused["hard.txt"] == "hard_linked"
    if (world.place / "sym.txt").exists() or os.path.lexists(world.place / "sym.txt"):
        assert refused["sym.txt"] == "reparse_point"
    assert (dest / "base" / "a.txt").read_bytes() == b"alpha\n"  # the replace ref changed nothing
    assert report["ok"] and result["state_same"] is True
    written = _everything_written(world, result, dest) + repr(state).encode()
    assert world.secret not in written


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions are Windows behaviour")
def test_a_tracked_folder_swapped_for_a_junction_is_refused_not_followed(world):
    write(world.root / "Documents" / "c.py", world.secret)
    remove_tree(world.place / "b")
    create_junction(world.place / "b", world.root / "Documents")
    result = capture_tree(world.place, world.settings(), world.main_git)
    manifest = load_manifest(world.keep, result["id"])[1]
    assert {"path": "b", "code": "reparse_point"} in manifest["refused"]
    assert "b/c.py" not in {h["path"] for h in manifest["holdings"]}  # not followed, and not called deleted
    assert world.secret not in _everything_written(world, result)


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions are Windows behaviour")
def test_folder_capture_never_follows_a_junction(world):
    folder = world.root / "scratch"
    write(folder / "mine.txt", "mine")
    create_junction(folder / "docs", world.root / "Documents")
    result = capture_folder(folder, world.settings())
    manifest = load_manifest(world.keep, result["id"])[1]
    assert [h["path"] for h in manifest["holdings"]] == ["mine.txt"]
    assert manifest["refused"] == [{"path": "docs", "code": "reparse_point"}]
    assert world.secret not in _everything_written(world, result)


@pytest.mark.skipif(not IS_WINDOWS, reason="alternate data streams are an NTFS behaviour")
def test_a_downloaded_file_is_saved_main_stream_only(world, tmp_path):
    folder = world.root / "downloads"
    write(folder / "report.txt", "the main stream")
    with open(str(folder / "report.txt") + ":Zone.Identifier", "w", encoding="utf-8") as stream:
        stream.write("[ZoneTransfer]\nZoneId=3\n")
    result = capture_folder(folder, world.settings())
    assert restore(world.keep, result["id"], tmp_path / "back")["ok"]
    assert (tmp_path / "back" / "files" / "report.txt").read_bytes() == b"the main stream"
    assert b"ZoneTransfer" not in _everything_written(world, result)


def test_a_worktree_pointing_somewhere_unregistered_reads_unreadable(world):
    markers = world.root / "markers"
    markers.mkdir()
    wt = world.root / "wt"
    fixture_git(world.main, "worktree", "add", "-q", "-b", "wtb", str(wt))
    evil = world.root / "attacker-gitdir"
    write(evil / "HEAD", "ref: refs/heads/dev\n")
    write(evil / "commondir", world.main_git.as_posix() + "\n")
    write(evil / "config", f"[core]\n\tfsmonitor = {_marker(markers, 'pointer')}\n")
    (wt / ".git").unlink()  # git for Windows marks it hidden, which a plain overwrite cannot open
    write(wt / ".git", f"gitdir: {evil.as_posix()}\n")
    with pytest.raises(Unreadable, match="points somewhere Thomas did not register"):
        capture_tree(wt, world.settings(), world.main_git)
    with pytest.raises(Unreadable, match="registration"):
        capture_tree(wt, world.settings(), None)
    assert list(markers.iterdir()) == [] and list(world.keep.iterdir()) == []


def test_a_git_folder_that_redirects_reads_unreadable(world):
    write(world.place / ".git" / "commondir", "../../elsewhere\n")
    with pytest.raises(Unreadable, match="commondir"):
        capture_tree(world.place, world.settings(), world.main_git)


@pytest.mark.parametrize("line", ["\\\\127.0.0.1\\share\\objects", "//127.0.0.1/share/objects", '"C:/quoted"'])
def test_alternates_that_leave_this_machine_read_unreadable(world, line):
    """Git would open a share someone else names, as you: refused before any git call or file access to it."""
    write(world.place / ".git" / "objects" / "info" / "alternates", line + "\n")
    with pytest.raises(Unreadable, match="not a plain local folder"):
        capture_tree(world.place, world.settings(), world.main_git)
    assert list(world.keep.iterdir()) == []


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions are Windows behaviour")
def test_alternates_through_a_junction_read_unreadable(world):
    (world.root / "other-objects").mkdir()
    create_junction(world.root / "objects-link", world.root / "other-objects")
    write(world.main_git / "objects" / "info" / "alternates", (world.root / "objects-link").as_posix() + "\n")
    with pytest.raises(Unreadable, match="not a plain folder"):
        capture_tree(world.place, world.settings(), world.main_git)  # the main repository is checked too


def test_reftable_reads_unreadable_until_it_is_supported(world):
    (world.place / ".git" / "reftable").mkdir()
    with pytest.raises(Unreadable, match="reftable"):
        capture_tree(world.place, world.settings(), world.main_git)


class _Flipping:
    """The real seam, except that reading ``target`` appends to it right after: a file someone is saving."""

    def __init__(self, target: Path) -> None:
        self.inner, self.target = keeper_fs(), target

    def hold_dir(self, path: Path):
        return self.inner.hold_dir(path)

    def read_regular(self, path: Path, limit: int) -> bytes:
        data = self.inner.read_regular(path, limit)
        if os.path.normcase(str(path)) == os.path.normcase(str(self.target)):
            with open(self.target, "ab") as handle:
                handle.write(b"+")
        return data


def test_a_file_that_changes_mid_read_is_detected(tmp_path):
    busy = write(tmp_path / "busy.txt", "start")
    with pytest.raises(UnsafeEntry) as caught:
        read_stable(_Flipping(busy), busy)
    assert caught.value.code == "changed_while_reading"


def test_capture_refuses_a_file_that_keeps_changing_and_says_the_place_moved(world):
    target = world.place / "new.txt"
    result = capture_tree(world.place, world.settings(fs=_Flipping(target)), world.main_git)
    manifest = load_manifest(world.keep, result["id"])[1]
    assert {"path": "new.txt", "code": "changed_while_reading"} in manifest["refused"]
    assert "new.txt" not in {h["path"] for h in manifest["holdings"]}
    assert result["state_same"] is False
