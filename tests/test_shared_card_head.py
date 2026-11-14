"""Reading fixture refs avoids Git processes without caching a moving HEAD."""

from pathlib import Path

import pytest

from tests import shared_card_support as support


def test_loose_head_is_read_again_after_it_moves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    refs = repo / ".git" / "refs" / "heads"
    refs.mkdir(parents=True)
    head = repo / ".git" / "HEAD"
    head.write_text("ref: refs/heads/dev\n", encoding="ascii")
    ref = refs / "dev"
    calls = []
    monkeypatch.setattr(support, "git", lambda *args: calls.append(args))
    ref.write_text("a" * 40 + "\n", encoding="ascii")
    assert support._head(repo) == "a" * 40
    ref.write_text("b" * 40 + "\n", encoding="ascii")
    assert support._head(repo) == "b" * 40
    head.write_text("c" * 40 + "\n", encoding="ascii")
    assert support._head(repo) == "c" * 40
    assert calls == []


@pytest.mark.parametrize("head", ["ref: refs/heads/dev\n", "unfamiliar layout\n"])
def test_other_ref_layouts_defer_to_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, head: str) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(head, encoding="ascii")
    calls = []

    def git(*args):
        calls.append(args)
        return "d" * 40

    monkeypatch.setattr(support, "git", git)
    assert support._head(tmp_path) == "d" * 40
    assert calls == [(tmp_path, "rev-parse", "HEAD")]


def test_linked_worktree_defers_to_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="ascii")
    calls = []

    def git(*args):
        calls.append(args)
        return "e" * 40

    monkeypatch.setattr(support, "git", git)
    assert support._head(tmp_path) == "e" * 40
    assert calls == [(tmp_path, "rev-parse", "HEAD")]
