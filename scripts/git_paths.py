#!/usr/bin/env python3
"""Resolve Git metadata paths safely across normal repos and linked worktrees."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent


def _run_git(repo_root: Path, args: tuple[str, ...]) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    text = str(proc.stdout or "").strip()
    return text or None


def _resolve_from_dotgit(repo_root: Path) -> Path | None:
    dotgit = repo_root / ".git"
    if dotgit.is_dir():
        return dotgit.resolve()
    if not dotgit.is_file():
        return None

    try:
        raw = dotgit.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None

    prefix = "gitdir:"
    if not raw.lower().startswith(prefix):
        return None

    gitdir_text = raw[len(prefix) :].strip()
    if not gitdir_text:
        return None

    gitdir = Path(gitdir_text)
    if not gitdir.is_absolute():
        gitdir = (repo_root / gitdir).resolve()
    return gitdir


@lru_cache(maxsize=32)
def resolve_git_dir(repo_root: Path | str = ROOT) -> Path:
    root = Path(repo_root).resolve()

    dotgit_resolved = _resolve_from_dotgit(root)
    if dotgit_resolved is not None:
        return dotgit_resolved

    absolute = _run_git(root, ("rev-parse", "--absolute-git-dir"))
    if absolute:
        return Path(absolute).resolve()

    relative = _run_git(root, ("rev-parse", "--git-dir"))
    if relative:
        path = Path(relative)
        if not path.is_absolute():
            path = (root / path).resolve()
        return path

    return (root / ".git").resolve()


@lru_cache(maxsize=64)
def resolve_git_path(pathspec: str, repo_root: Path | str = ROOT) -> Path:
    root = Path(repo_root).resolve()
    spec = str(pathspec or "").strip()
    if not spec:
        return resolve_git_dir(root)

    git_path = _run_git(root, ("rev-parse", "--git-path", spec))
    if git_path:
        path = Path(git_path)
        if not path.is_absolute():
            path = (root / path).resolve()
        return path

    return (resolve_git_dir(root) / Path(spec)).resolve()


def is_git_repo(repo_root: Path | str = ROOT) -> bool:
    git_dir = resolve_git_dir(repo_root)
    return git_dir.exists()
