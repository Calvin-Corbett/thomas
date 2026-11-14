"""``head_sha`` must give exactly what ``git rev-parse HEAD`` gives, without starting git."""

from __future__ import annotations

import subprocess
from pathlib import Path

from thomas.core import head_sha as module
from thomas.core.head_sha import head_sha

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(root: Path, *args: str) -> str:
    import os

    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, env={**os.environ, **ENV}
    )
    return done.stdout.strip()


def repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    git(tmp_path, "init", "-q", "-b", "dev")
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    git(tmp_path, "add", "a.txt")
    git(tmp_path, "commit", "-q", "-m", "one")
    return tmp_path


def test_it_matches_git_and_follows_a_new_commit(tmp_path):
    root = repo(tmp_path)
    assert head_sha(root) == git(root, "rev-parse", "HEAD")
    (root / "a.txt").write_text("2", encoding="utf-8")
    git(root, "commit", "-q", "-am", "two")
    assert head_sha(root) == git(root, "rev-parse", "HEAD")


def test_it_reads_packed_refs_after_a_pack(tmp_path):
    root = repo(tmp_path)
    git(root, "pack-refs", "--all")
    assert head_sha(root) == git(root, "rev-parse", "HEAD")


def test_it_reads_a_linked_worktree_and_a_detached_head(tmp_path):
    root = repo(tmp_path / "main")
    other = tmp_path / "linked"
    git(root, "worktree", "add", "-q", "-b", "side", str(other))
    assert head_sha(other) == git(other, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "--detach")
    assert head_sha(root) == git(root, "rev-parse", "HEAD")


def test_it_says_nothing_rather_than_guess(tmp_path):
    assert head_sha(tmp_path) is None  # not a checkout: the caller asks git, as before


def test_a_second_ask_does_not_reread_the_ref(tmp_path, monkeypatch):
    root = repo(tmp_path)
    head_sha(root)
    monkeypatch.setattr(module, "_ref_value", lambda *a: (_ for _ in ()).throw(AssertionError("re-read")))
    assert head_sha(root) == git(root, "rev-parse", "HEAD")
