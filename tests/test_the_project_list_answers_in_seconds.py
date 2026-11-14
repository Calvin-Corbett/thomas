"""The shared sibling scan reuses fresh copy reads while retaining its file list."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from thomas.server import green_checkout, green_handoff


def _copies(root: Path, count: int = 20) -> list[green_checkout.Green]:
    copies = []
    for number in range(count):
        name = f"exec-{number:02d}"
        git_dir = root / "git" / name
        work = root / "work" / name
        git_dir.mkdir(parents=True)
        work.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/dev\n", encoding="ascii")
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "refs" / "heads" / "dev").write_text(f"{number:040x}\n", encoding="ascii")
        (git_dir / "index").write_bytes(b"index")
        copies.append(green_checkout.Green(name, work, git_dir, "base", root))
    return copies


def test_twenty_copies_are_bounded_cached_and_still_answer_identically(tmp_path, monkeypatch, capsys):
    root = tmp_path / "one"
    copies = _copies(root)
    by_name = {copy.execution_id: copy for copy in copies}
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "_found", by_name.get)
    monkeypatch.setattr(green_handoff, "_read_state", lambda git_dir: {})
    moment = [1000.0]
    monkeypatch.setattr(green_handoff, "_sibling_clock", lambda: moment[0], raising=False)
    lock = threading.Lock()
    calls: list[tuple[str, str]] = []
    in_flight = peak = 0

    def read_git(green, *args):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
            calls.append((green.execution_id, args[0]))
        time.sleep(0.2)
        with lock:
            in_flight -= 1
        if args[0] == "diff":
            return "shared.txt\0tracked.txt\0"
        return "shared.txt\0added.txt\0"

    monkeypatch.setattr(green_handoff, "_green_git", read_git)
    expected = {copy.execution_id: ["shared.txt", "tracked.txt", "added.txt"] for copy in copies}

    started = time.monotonic()
    assert green_handoff.sibling_changes("") == expected
    first_time = time.monotonic() - started
    assert len(calls) == 40
    assert all(sum(name == copy.execution_id for name, _ in calls) == 2 for copy in copies)
    assert green_handoff.sibling_changes("") == expected
    assert len(calls) == 40
    assert 1 < peak <= green_handoff._SIBLING_WORKERS
    assert first_time < 6

    head = copies[0].git_dir / "refs" / "heads" / "dev"
    head.write_text("f" * 40 + "\n", encoding="ascii")
    assert green_handoff.sibling_changes("") == expected
    assert calls[-2:] == [(copies[0].execution_id, "diff"), (copies[0].execution_id, "ls-files")]
    assert len(calls) == 42

    index = copies[1].git_dir / "index"
    index.write_bytes(b"longer index")
    assert green_handoff.sibling_changes("") == expected
    assert len(calls) == 44
    assert calls[-2:] == [(copies[1].execution_id, "diff"), (copies[1].execution_id, "ls-files")]

    for copy in copies:
        assert green_handoff.sibling_changes(copy.execution_id) == {
            name: files for name, files in expected.items() if name != copy.execution_id
        }
    assert len(calls) == 44

    moment[0] += green_handoff._SIBLING_FRESH_S + 1
    assert green_handoff.sibling_changes("") == expected
    assert len(calls) == 84
    print(f"20 copies: first={first_time:.2f}s, git calls=40/0/2/2/0/40, peak={peak}")


def test_packed_ref_commit_invalidates_cached_copy(tmp_path, monkeypatch):
    root = tmp_path / "packed"
    copy = _copies(root, 1)[0]
    (copy.git_dir / "refs" / "heads" / "dev").unlink()
    packed = copy.git_dir / "packed-refs"
    packed.write_text(f"{'a' * 40} refs/heads/dev\n", encoding="ascii")
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "_found", lambda _: copy)
    monkeypatch.setattr(green_handoff, "_read_state", lambda _: {})
    calls = []

    def read_git(green, *args):
        calls.append(args[0])
        return "changed.txt\0"

    monkeypatch.setattr(green_handoff, "_green_git", read_git)
    assert green_handoff.sibling_changes("") == {copy.execution_id: ["changed.txt"]}
    assert green_handoff.sibling_changes("") == {copy.execution_id: ["changed.txt"]}
    assert calls == ["diff", "ls-files"]
    packed.write_text(f"{'b' * 40} refs/heads/dev\n", encoding="ascii")
    assert green_handoff.sibling_changes("") == {copy.execution_id: ["changed.txt"]}
    assert calls == ["diff", "ls-files"] * 2


def test_exclusions_and_two_roots_do_not_share_cached_files(tmp_path, monkeypatch):
    left, right = tmp_path / "left", tmp_path / "right"
    copies = _copies(left, 3)
    other = _copies(right, 1)[0]
    assert copies[0].execution_id == other.execution_id
    scratch = left / "git" / f"{green_handoff.SCRATCH_PREFIX}temporary"
    scratch.mkdir()
    root = [left]
    monkeypatch.setattr(green_checkout, "green_root", lambda: root[0])
    monkeypatch.setattr(
        green_handoff,
        "_found",
        lambda name: next(
            (copy for copy in (copies if root[0] == left else [other]) if copy.execution_id == name), None
        ),
    )
    declined = set()
    monkeypatch.setattr(
        green_handoff, "_read_state", lambda git_dir: {"status": "declined"} if git_dir.name in declined else {}
    )
    calls = []

    def read_git(green, *args):
        calls.append((green.git_dir, args[0]))
        return "different.txt\0" if green.git_dir == other.git_dir else "same.txt\0"

    monkeypatch.setattr(green_handoff, "_green_git", read_git)
    assert green_handoff.sibling_changes("") == {copy.execution_id: ["same.txt"] for copy in copies}
    assert len(calls) == 6
    declined.add(copies[0].execution_id)
    (copies[1].git_dir / green_checkout.SETTLED_NAME).touch()
    assert green_handoff.sibling_changes("") == {copies[2].execution_id: ["same.txt"]}
    assert len(calls) == 6
    root[0] = right
    declined.clear()
    assert green_handoff.sibling_changes("") == {other.execution_id: ["different.txt"]}
    assert len(calls) == 8


def test_concurrent_callers_share_the_cached_copy(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    root = tmp_path / "threads"
    copy = _copies(root, 1)[0]
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "_found", lambda _: copy)
    monkeypatch.setattr(green_handoff, "_read_state", lambda _: {})
    calls = []

    def read_git(green, *args):
        calls.append(args[0])
        time.sleep(0.02)
        return "same.txt\0"

    monkeypatch.setattr(green_handoff, "_green_git", read_git)
    with ThreadPoolExecutor(max_workers=8) as callers:
        assert (
            list(callers.map(lambda _: green_handoff.sibling_changes(""), range(8)))
            == [{copy.execution_id: ["same.txt"]}] * 8
        )
    assert calls == ["diff", "ls-files"]


def test_unanswered_git_read_is_not_cached(tmp_path, monkeypatch):
    root = tmp_path / "green"
    copy = _copies(root, 1)[0]
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "_found", lambda _: copy)
    monkeypatch.setattr(green_handoff, "_read_state", lambda _: {})
    reads = []

    def read_git(green, *args):
        reads.append(args[0])
        if args[0] == "diff" and len(reads) == 1:
            return None
        return "untracked.txt\0" if args[0] == "ls-files" else "tracked.txt\0"

    monkeypatch.setattr(green_handoff, "_green_git", read_git)
    assert green_handoff.sibling_changes("") == {copy.execution_id: ["untracked.txt"]}
    assert green_handoff.sibling_changes("") == {copy.execution_id: ["tracked.txt", "untracked.txt"]}
    assert green_handoff.sibling_changes("") == {copy.execution_id: ["tracked.txt", "untracked.txt"]}
    assert reads == ["diff", "ls-files", "diff", "ls-files"]


def test_worktree_stamp_error_retries_cached_copy_with_git(tmp_path, monkeypatch):
    root = tmp_path / "stamp-error"
    copy = _copies(root, 1)[0]
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "_found", lambda _: copy)
    monkeypatch.setattr(green_handoff, "_read_state", lambda _: {})
    calls = []

    def read_git(green, *args):
        calls.append(args[0])
        return "still-in-play.txt\0"

    monkeypatch.setattr(green_handoff, "_green_git", read_git)
    expected = {copy.execution_id: ["still-in-play.txt"]}
    assert green_handoff.sibling_changes("") == expected
    assert calls == ["diff", "ls-files"]

    def failed_stamp(work):
        raise FileNotFoundError(work / "file-removed-during-walk")

    monkeypatch.setattr(green_handoff, "_worktree_stamp", failed_stamp)
    assert green_handoff.sibling_changes("") == expected
    assert calls == ["diff", "ls-files", "diff", "ls-files"]
