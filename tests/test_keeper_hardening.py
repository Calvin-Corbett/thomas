"""Regression tests for the security review of keeper capture v1 (P0.3): the size cap, the free-space floor and memory.

One section per finding, named by its id; the other findings are in ``test_keeper_hardening_git_facts.py``,
``test_keeper_hardening_private.py`` and ``test_keeper_hardening_place_reads.py``. Each test fails on the code the
review read and passes on the fix.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from scripts.keeper import capture as capture_mod
from scripts.keeper import capture_steps, gitplace
from scripts.keeper import capture_tree as capture_tree_mod
from scripts.keeper.capture import CaptureRefused, capture_tree, main
from scripts.keeper.keep import ArchiveWriter

# world is a pytest fixture, shared through keeper_support
from tests.keeper_support import _manifest, _refused, fixture_git, git_binary, keep_files, world, write


class _CountingArchive(ArchiveWriter):
    adds: list[str] = []

    def add(self, name, data, **facts):
        type(self).adds.append(name)
        return super().add(name, data, **facts)


# --- size-cap-enforced-after-full-archive-written ---------------------------------------------------------------


def test_the_cap_stops_the_archive_as_it_grows_not_after(world, monkeypatch):
    for number in range(40):
        write(world.place / "big" / f"blob{number}.bin", os.urandom(50_000))  # 2 MB that will not compress
    seen: list[int] = []
    real_check = capture_mod.Budget.check

    def watching(self, on_disk, incoming=0, *, exact=False):
        seen.append(on_disk)
        return real_check(self, on_disk, incoming, exact=exact)

    monkeypatch.setattr(capture_mod.Budget, "check", watching)
    cap = 200_000
    with pytest.raises(CaptureRefused, match="over the"):
        capture_tree(world.place, world.settings(cap_bytes=cap), world.main_git)
    assert max(seen) <= cap + 50_000 + 4096  # never more than one entry past the cap, where the review saw 10x
    assert keep_files(world.keep) == [] and list(world.work.iterdir()) == []


def test_the_floor_is_watched_on_the_work_drive_while_the_archive_is_written(world, monkeypatch):
    for number in range(30):
        write(world.place / "many" / f"f{number}.txt", f"only copy {number}\n" * 50)
    asked: list[str] = []

    def disk(path):
        asked.append(os.path.normcase(str(path)))
        return SimpleNamespace(total=100 * 2**30, used=0, free=(10 * 2**30 if len(asked) < 12 else 2**20))

    monkeypatch.setattr(capture_mod.shutil, "disk_usage", disk)
    monkeypatch.setattr(capture_steps, "ArchiveWriter", _CountingArchive)
    _CountingArchive.adds = []
    with pytest.raises(CaptureRefused, match="floor"):
        capture_tree(world.place, world.settings(min_free_bytes=2**30), world.main_git)
    assert 0 < len(_CountingArchive.adds) < 30  # stopped part way, not after the whole place was written
    work = os.path.normcase(str(world.work))
    assert all(p.startswith(work) for p in asked)  # the drive judged is the work folder's, not only the keep's
    assert keep_files(world.keep) == [] and list(world.work.iterdir()) == []


def test_a_work_drive_already_under_the_floor_writes_nothing(world, monkeypatch):
    def began(*_a, **_k):
        raise AssertionError("the capture started writing on a drive already under the floor")

    monkeypatch.setattr(capture_mod.shutil, "disk_usage", lambda _p: SimpleNamespace(total=1, used=0, free=2**20))
    monkeypatch.setattr(capture_tree_mod, "make_view", began)
    with pytest.raises(CaptureRefused, match="floor"):
        capture_tree(world.place, world.settings(min_free_bytes=2**30), world.main_git)
    assert list(world.work.iterdir()) == [] and keep_files(world.keep) == []


def test_a_bundle_over_the_cap_is_refused_before_git_writes_it(world, monkeypatch):
    write(world.place / "history.bin", os.urandom(600_000))
    fixture_git(world.place, "add", "history.bin")
    fixture_git(world.place, "commit", "-q", "-m", "a big commit dev does not have")
    written = []
    monkeypatch.setattr(capture_tree_mod, "write_bundle", lambda *a: written.append(a) or [])
    with pytest.raises(CaptureRefused, match="over the"):
        capture_tree(world.place, world.settings(cap_bytes=300_000), world.main_git)
    assert written == [] and keep_files(world.keep) == []


# --- unbounded-metadata-reads-can-oom ----------------------------------------------------------------------------


def test_an_index_over_its_limit_is_listed_and_the_files_still_saved(world, monkeypatch):
    monkeypatch.setattr(capture_tree_mod, "INDEX_LIMIT", 64)
    manifest = _manifest(world, capture_tree(world.place, world.settings(), world.main_git))
    problem = next(r for r in manifest["refused"] if r["path"] == "git:index")
    assert "too_large" in problem["detail"] and "new.txt" in {h["path"] for h in manifest["holdings"]}


def test_a_base_too_large_to_hold_is_listed_and_never_read(world, monkeypatch):
    write(world.place / "big.txt", "x" * 2_000_000)
    fixture_git(world.place, "add", "big.txt")
    fixture_git(world.place, "commit", "-q", "-m", "a big file")
    write(world.place / "big.txt", "small now\n")
    fetched: list[str] = []
    real_cat = gitplace.cat_blobs
    monkeypatch.setattr(gitplace, "cat_blobs", lambda runner, oids: fetched.extend(oids) or real_cat(runner, oids))
    big = fixture_git(world.place, "rev-parse", "HEAD:big.txt")
    manifest = _manifest(world, capture_tree(world.place, world.settings(file_limit=1_000_000), world.main_git))
    assert _refused(manifest)["big.txt"] == "base_too_large" and big not in fetched
    assert "files/big.txt" in {e["stored"] for e in manifest["entries"]}
    assert "base/big.txt" not in {e["stored"] for e in manifest["entries"]}


def test_running_out_of_memory_is_a_clean_refusal(world, monkeypatch, capsys):
    def exhausted(*_a, **_k):
        raise MemoryError("too big to hold")

    monkeypatch.setattr(capture_mod, "capture_tree", exhausted)
    common = ["--keep", str(world.keep), "--work", str(world.work), "--git", git_binary()]
    assert main(["tree", str(world.place), *common]) == 2
    assert json.loads(capsys.readouterr().out)["refused"] == "MemoryError: too big to hold"
