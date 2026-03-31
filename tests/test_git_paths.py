from __future__ import annotations

from pathlib import Path

import scripts.git_paths as mod


def test_resolve_git_dir_uses_real_dotgit_directory(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    mod.resolve_git_dir.cache_clear()
    mod.resolve_git_path.cache_clear()
    try:
        assert mod.resolve_git_dir(tmp_path) == git_dir.resolve()
        assert mod.resolve_git_path("hooks/post-commit", tmp_path) == (git_dir / "hooks" / "post-commit").resolve()
    finally:
        mod.resolve_git_dir.cache_clear()
        mod.resolve_git_path.cache_clear()


def test_resolve_git_dir_handles_linked_worktree_pointer_file(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git-data" / "worktrees" / "discord-pass"
    git_dir.mkdir(parents=True)
    (tmp_path / ".git").write_text("gitdir: .git-data/worktrees/discord-pass\n", encoding="utf-8")

    mod.resolve_git_dir.cache_clear()
    mod.resolve_git_path.cache_clear()
    try:
        assert mod.resolve_git_dir(tmp_path) == git_dir.resolve()
        assert mod.resolve_git_path("hooks/post-commit", tmp_path) == (git_dir / "hooks" / "post-commit").resolve()
    finally:
        mod.resolve_git_dir.cache_clear()
        mod.resolve_git_path.cache_clear()
