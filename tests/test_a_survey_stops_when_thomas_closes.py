"""A long git survey stops when Thomas is closing, instead of holding the shutdown open.

On 2026-11-09 the server behind your desktop app wrote its exit record at 19:54 and was still alive 261 seconds later.
Its own stack snapshots (``shutdown-42104-*.txt``) showed what was running: the survey of every self-fix copy, with
eight git reads at once two minutes in (``green_handoff.sibling_changes``), and the ratchet's survey of about 150 old
branches (``ratchet.candidates.discover``). Both only read, neither looked at whether the server was closing, and
Python waits for such threads before it exits. Until the old server is gone the next one cannot start.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.ratchet_support import git, make_repo, on_ref
from thomas.server import green_handoff
from thomas.server.precard import workers
from thomas.server.ratchet import candidates
from thomas.server.ratchet.gitrepo import GitFailed, Repo


def test_closing_is_read_from_any_thread_and_follows_the_newest_server() -> None:
    first, seen = threading.Event(), []
    with workers.generation(first):
        assert workers.closing() is False
        first.set()
        reader = threading.Thread(target=lambda: seen.append(workers.closing()))
        reader.start()
        reader.join()
        assert seen == [True]
        with workers.generation(threading.Event()):  # a server that started after the old one began to close
            assert workers.closing() is False


def test_a_copy_is_not_read_once_thomas_is_closing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(green_handoff, "_green_git", lambda *args: calls.append(args) or "")
    monkeypatch.setattr(workers, "closing", lambda: True)
    assert green_handoff._sibling_files(object()) == ((), False)  # not answered, so nothing is remembered for it
    assert calls == []


def test_walking_a_copy_stops_once_thomas_is_closing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "file.txt").write_text("x", encoding="utf-8")
    assert green_handoff._worktree_stamp(tmp_path)
    monkeypatch.setattr(workers, "closing", lambda: True)
    with pytest.raises(OSError):
        green_handoff._worktree_stamp(tmp_path)


def test_the_survey_of_copies_starts_nothing_once_thomas_is_closing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "green"
    (root / "git" / "thomas-one").mkdir(parents=True)
    monkeypatch.setattr(green_handoff.green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "_read_state", lambda _dir: {})
    stamped: list[Path] = []
    monkeypatch.setattr(green_handoff, "_sibling_stamp", lambda git_dir: stamped.append(git_dir))
    monkeypatch.setattr(workers, "closing", lambda: True)
    assert green_handoff.sibling_changes("") == {}
    assert stamped == []


def test_the_branch_survey_stops_once_thomas_is_closing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    on_ref(repo, "refs/heads/fix/small", base, {"thomas/core/widget.py": "VALUE = 2\n"}, "small")
    candidates.discover(Repo(repo))  # it runs to its end while Thomas is running
    monkeypatch.setattr(workers, "closing", lambda: True)
    with pytest.raises(GitFailed, match="closing"):
        candidates.discover(Repo(repo))
