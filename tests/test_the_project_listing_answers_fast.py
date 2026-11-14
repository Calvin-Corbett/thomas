"""The self-project listing keeps its answers while green scans get cheaper and fresher."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

from thomas.server import green_checkout, green_handoff
from thomas.server.routes import self_project_routes


# Verbatim _worktree_stamp from dev, for byte-for-byte compatibility checks.
def _dev_worktree_stamp(work: Path) -> bytes:
    digest = hashlib.blake2b(digest_size=16)
    pending = [work]
    while pending:
        folder = pending.pop()
        for entry in sorted(os.scandir(folder), key=lambda item: item.name):
            if entry.name == ".git" and folder == work:
                continue
            stat = entry.stat(follow_symlinks=False)
            digest.update(str(Path(entry.path).relative_to(work)).encode("utf-8", errors="surrogateescape"))
            digest.update(f":{stat.st_mode}:{stat.st_size}:{stat.st_mtime_ns}\0".encode("ascii"))
            if entry.is_dir(follow_symlinks=False):
                pending.append(Path(entry.path))
    return digest.digest()


@pytest.fixture
def greens(tmp_path, monkeypatch):
    root = tmp_path / "greens"
    copies = []
    for number in range(2):
        name = f"exec-{number:02d}"
        git_dir, work = root / "git" / name, root / "work" / name
        (git_dir / "refs" / "heads").mkdir(parents=True)
        work.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/dev\n", encoding="ascii")
        (git_dir / "refs" / "heads" / "dev").write_text(f"{number:040x}\n", encoding="ascii")
        (git_dir / "index").write_bytes(b"index")
        copies.append(green_checkout.Green(name, work, git_dir, "base", root))
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "_found", {copy.execution_id: copy for copy in copies}.get)
    monkeypatch.setattr(green_handoff, "_read_state", lambda _dir: {})
    monkeypatch.setattr(green_handoff, "_sibling_cache", {})
    monkeypatch.setattr(green_handoff, "_sibling_clock", lambda: 1000.0)
    return root, copies


def _git_answers(monkeypatch):
    calls = []

    def git(green, *args):
        calls.append((green.execution_id, args[0]))
        return f"{green.execution_id}-tracked.txt\0" if args[0] == "diff" else "added.txt\0"

    monkeypatch.setattr(green_handoff, "_green_git", git)
    return calls


def test_stamp_matches_dev_on_nested_unicode_empty_and_git(tmp_path):
    work = tmp_path / "work"
    (work / "nested" / ".git").mkdir(parents=True)
    (work / "empty").mkdir()
    (work / "nested" / ".git" / "inside").write_text("nested", encoding="utf-8")
    (work / "nested" / "café.txt").write_text("hello", encoding="utf-8")
    (work / ".git").write_text("not a folder", encoding="ascii")
    _dev_worktree_stamp(work)  # warm the same fixture for both implementations
    assert green_handoff._worktree_stamp(work) == _dev_worktree_stamp(work)
    (work / ".git").write_text("this top-level file is skipped", encoding="ascii")
    assert green_handoff._worktree_stamp(work) == _dev_worktree_stamp(work)


def test_read_projects_report_identical_to_dev_on_first_and_repeat(greens, monkeypatch):
    root, copies = greens
    catalog = root / "catalog"
    conversations = catalog / ".thomas" / "evolve" / "agent" / "conversations"
    conversations.mkdir(parents=True)
    for number, copy in enumerate(copies):
        folder = copy.work / ".thomas" / "evolve" / "agent" / "conversations"
        folder.mkdir(parents=True)
        cid = f"fc_{number}"
        (folder / f"{cid}.json").write_text(
            json.dumps(
                {
                    "id": cid,
                    "title": f"Project {number}",
                    "updated_at": f"2026-10-{number + 1:02d}",
                    "thomas_project": {"execution_id": copy.execution_id},
                }
            ),
            encoding="utf-8",
        )
    (conversations / "fc_old.json").write_text(
        json.dumps(
            {
                "id": "fc_old",
                "title": "Older",
                "updated_at": "2026-09-01",
                "thomas_project": {"execution_id": "retired", "retirement": {"outcome": "reported", "reason": "done"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        self_project_routes.thomas_project, "project_phase", lambda *_: ("waiting", "a Build run is going")
    )
    _git_answers(monkeypatch)
    original = green_handoff._worktree_stamp

    def report_with(stamp):
        monkeypatch.setattr(green_handoff, "_worktree_stamp", stamp)
        green_handoff._sibling_cache.clear()
        return (self_project_routes.read_projects(catalog), self_project_routes.read_projects(catalog))

    expected = report_with(_dev_worktree_stamp)
    actual = report_with(original)
    assert actual == expected
    assert [row["state"] for row in actual[0]["projects"]] == ["running", "running", "reported"]
    assert [row["changed_files"] for row in actual[0]["projects"]] == [
        [f"{copy.execution_id}-tracked.txt", "added.txt"] for copy in reversed(copies)
    ] + [[]]


def _profile_calls(stamp, work):
    calls = 0

    def profile(_frame, event, _arg):
        nonlocal calls
        if event in ("call", "c_call"):
            calls += 1

    sys.setprofile(profile)
    try:
        stamp(work)
    finally:
        sys.setprofile(None)
    return calls


def test_stamp_stays_under_twenty_calls_per_entry(tmp_path):
    work = tmp_path / "big"
    work.mkdir()
    for number in range(2100):
        (work / f"file-{number:04d}").touch()
    old_calls = _profile_calls(_dev_worktree_stamp, work)
    new_calls = _profile_calls(green_handoff._worktree_stamp, work)
    assert old_calls / 2100 > 100
    assert new_calls / 2100 <= 20


def test_each_green_is_stamped_only_once_per_listing(greens, monkeypatch):
    _, copies = greens
    _git_answers(monkeypatch)
    original = green_handoff._worktree_stamp
    stamps = Counter()

    def stamp(work):
        stamps[work] += 1
        return original(work)

    monkeypatch.setattr(green_handoff, "_worktree_stamp", stamp)
    for changed in (False, False, True):
        stamps.clear()
        if changed:
            (copies[0].work / "new.txt").write_text("added", encoding="ascii")
        green_handoff.sibling_changes("")
        assert stamps == Counter({copy.work: 1 for copy in copies})


def test_git_write_during_read_is_visible_on_next_call(greens, monkeypatch):
    _, copies = greens
    copy = copies[0]
    calls = []
    reads = 0

    def git(green, *args):
        nonlocal reads
        calls.append((green.execution_id, args[0]))
        if green == copy and args[0] == "ls-files":
            reads += 1
            if reads == 1:
                (copy.work / "written-during-git.txt").write_text("new", encoding="ascii")
                return ""
            return "written-during-git.txt\0"
        return "" if args[0] == "ls-files" else "tracked.txt\0"

    monkeypatch.setattr(green_handoff, "_green_git", git)
    assert green_handoff.sibling_changes("")[copy.execution_id] == ["tracked.txt"]
    calls.clear()
    # The preceding read's git call wrote the file after its answer was formed.
    assert green_handoff.sibling_changes("")[copy.execution_id] == ["tracked.txt", "written-during-git.txt"]
    assert calls.count((copy.execution_id, "ls-files")) == 1


@pytest.mark.parametrize("mutation", ["rewrite", "create", "delete"])
def test_worktree_mutation_refreshes_git_inside_sixty_seconds(greens, monkeypatch, mutation):
    _, copies = greens
    copy = copies[0]
    tracked = copy.work / "tracked.txt"
    tracked.write_text("before", encoding="ascii")
    calls = []
    answer = ["old.txt\0"]

    def git(green, *args):
        calls.append((green.execution_id, args[0]))
        return answer[0] if args[0] == "diff" else ""

    monkeypatch.setattr(green_handoff, "_green_git", git)
    assert green_handoff.sibling_changes("")[copy.execution_id] == ["old.txt"]
    calls.clear()
    answer[0] = "new.txt\0"
    if mutation == "rewrite":
        tracked.write_text("a different size than before", encoding="ascii")
    elif mutation == "create":
        (copy.work / "created.txt").write_text("new", encoding="ascii")
    else:
        tracked.unlink()
    assert green_handoff.sibling_changes("")[copy.execution_id] == ["new.txt"]
    assert calls == [(copy.execution_id, "diff"), (copy.execution_id, "ls-files")]


def test_unstampable_green_still_reads_git_and_retries(greens, monkeypatch):
    _, copies = greens
    copy = copies[0]
    original = green_handoff._worktree_stamp
    calls = _git_answers(monkeypatch)

    def stamp(work):
        if work == copy.work:
            raise PermissionError("work tree unavailable")
        return original(work)

    monkeypatch.setattr(green_handoff, "_worktree_stamp", stamp)
    for _ in range(2):
        assert green_handoff.sibling_changes("")[copy.execution_id] == ["exec-00-tracked.txt", "added.txt"]
    assert [call for call in calls if call[0] == copy.execution_id] == [
        (copy.execution_id, "diff"),
        (copy.execution_id, "ls-files"),
    ] * 2
    assert copy.git_dir not in green_handoff._sibling_cache
