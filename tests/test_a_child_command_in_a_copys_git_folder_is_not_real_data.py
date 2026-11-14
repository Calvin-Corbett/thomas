"""A command a test starts inside a check copy's own git folder has not touched your real data (2026-11-13).

The card check's copy of dev (``thomas/server/precard/scratch.py``, ``precard-<id>-base``) is a green: a clone made
with ``--separate-git-dir``, its files in LOCALAPPDATA/Thomas/green/work/<name> and its git folder in
LOCALAPPDATA/Thomas/green/git/<name>. Such a copy's ``git worktree list`` names the git folder as the main worktree,
so ``scripts/crew/worktree_ledger.py`` runs ``git status`` and ``git log -1 --format=%cI`` with that folder as their
working folder. a45888acf excused the copy's own git folder for opens in the test process and in Python children, and
not for the commands the test process starts: on 2026-11-14 dev's side ended "pytest exit 1 contradicts its report
(...\\green\\git\\precard-thomas-364bb91d5961-base was opened by this test run (a child command ... worktree_ledger.py
_run_git, tests/test_agent_startup_router.py::test_build_startup_payload_includes_preflight)".
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests import conftest as guard
from tests.ratchet_support import make_repo
from tests.test_a_check_copy_reading_its_own_git_folder_is_not_real_data import _copy
from thomas.server import green_checkout


def test_a_separate_git_folder_copy_lists_its_git_folder_as_a_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "greens"))
    copy = green_checkout.create_green(make_repo(tmp_path), "precard-copy-base")
    listed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=copy.work, capture_output=True, text=True, check=True
    )
    first = listed.stdout.splitlines()[0].removeprefix("worktree ")
    assert Path(first).resolve() == copy.git_dir.resolve()


def _started(cwd: Path, *args: str) -> None:
    subprocess.run([sys.executable, "-c", "pass", *args], cwd=str(cwd), capture_output=True, timeout=60, check=True)


def test_a_command_in_the_copys_own_git_folder_is_not_real_data_and_another_copys_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve() / "Thomas"
    checkout, git = _copy(root)
    other = root / "green" / "git" / "another-copy"
    other.mkdir()
    seen: set[str] = set()
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root,))
    monkeypatch.setattr(guard, "REAL_HOME_THOMAS_DIRS", ())
    monkeypatch.setattr(guard, "ROOT", checkout)
    monkeypatch.setattr(guard, "_OWN_GIT_FOLDER", git)
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", seen)

    _started(git, "--format=%cI", str(git / "HEAD"))
    assert seen == set()

    _started(other, "--format=%cI")
    assert str(other) in seen
    seen.clear()
    _started(checkout, str(other / "HEAD"))
    assert seen == {str(other / "HEAD")}
