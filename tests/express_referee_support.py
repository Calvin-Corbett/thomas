"""Helpers for the referee-core tests (package B1): a runner against the lab repository, decisions, cleanup.

The lab's git directory is real. The referee runner is an ``isolated_view`` of it kept under the lab's referee
folder, so every referee call runs against the lab's objects through the scrubbed wrapper. ``force_rmtree`` removes
a scratch folder holding read-only git object files (it clears the read-only bit on error) and never walks through
a junction: a junction is detached with ``os.rmdir`` first.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Mapping
from pathlib import Path

import pytest
from scripts.cage.referee.charter import Charter, Decision
from scripts.cage.referee.derive import evaluate
from scripts.cage.referee.gitenv import GitRunner, isolated_view

from tests.express_lab import ExpressLab
from tests.express_pytest import lab  # noqa: F401  (the lab fixture, re-exported for the test modules)
from tests.express_repo import TreeEntry
from tests.express_winfs import is_reparse_point

FRAGMENT = b"### Added\n- A plain change that is described in one sentence.\n"


def _clear_and_retry(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    func(path)


def force_rmtree(path: Path) -> None:
    """Delete a folder tree that may hold read-only files; detach any junction first instead of walking into it."""
    for dirpath, dirnames, _files in os.walk(path):
        for name in list(dirnames):
            if is_reparse_point(Path(dirpath, name)):
                os.rmdir(Path(dirpath, name))
                dirnames.remove(name)
    shutil.rmtree(path, onexc=_clear_and_retry)


@pytest.fixture
def git(lab: ExpressLab) -> GitRunner:  # noqa: F811
    private = lab.layout.referee / "private"
    private.mkdir(parents=True, exist_ok=True)
    yield isolated_view(lab.repo.git_path, lab.repo.root / ".git", private)
    force_rmtree(private)


def patch_adding(lab: ExpressLab, files: Mapping[str, bytes | None]) -> bytes:
    """A real ``git diff --binary`` that adds (or with None removes) these files on the lab's dev."""
    edits = {p: (lab.repo.entry(c) if c is not None else None) for p, c in files.items()}
    return lab.repo.patch_for(edits)


def decide(lab: ExpressLab, git: GitRunner, patch: bytes, charter: Charter | None = None) -> Decision:
    return evaluate(git, lab.repo.head(), patch, charter or Charter())


def world(lab: ExpressLab) -> tuple[str, str]:
    """The tip of dev and the working copy's status: what a demotion must leave exactly as it was."""
    return lab.repo.head(), lab.repo.text("status", "--porcelain")


def entry(lab: ExpressLab, data: bytes, mode: str = "100644") -> TreeEntry:
    return lab.repo.entry(data, mode)
