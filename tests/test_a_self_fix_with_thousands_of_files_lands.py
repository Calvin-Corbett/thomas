"""A self-fix that changes thousands of files is checked and lands, one git command line at a time.

Windows starts a program with a command line of at most 32,767 characters. On 2026-09-27 you approved the junk
sweep's card: 3,283 files, whose paths the promoter put on a single ``git diff`` line to look for uncommitted work in
the running copy. Windows refused to start git ("[WinError 206] The filename or extension is too long"), the
promoter recorded an error, and nothing you approved landed. ``blue_dirty``, ``already_in_running_copy`` and
``land`` now hand git the paths in batches that each fit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks

WINDOWS_LIMIT = 32_767
FILES = 1200
FOLDER = "thomas/marketplace/a_folder_deep_enough_to_make_every_path_long"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def _configure(repo: Path) -> None:
    for key, value in (
        ("user.name", "Thomas Test"),
        ("user.email", "test@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
    ):
        _git(repo, "config", key, value)


def _name(i: int) -> str:
    return f"{FOLDER}/module_{i:04d}.py"


@pytest.fixture
def big_change(tmp_path: Path) -> tuple[Path, str, str, list[tuple[str, str]]]:
    repo = tmp_path / "running"
    (repo / FOLDER).mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "dev")
    _configure(repo)
    for i in range(FILES):
        (repo / _name(i)).write_text(f"x = {i}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    parent = _git(repo, "rev-parse", "HEAD").strip()
    # The approved change, made the promoter's way: a commit object dev does not point at yet. Even files are
    # edited, odd ones deleted, and as many new files are added, so every list land() passes to git is too long.
    scratch = tmp_path / "scratch"
    _git(tmp_path, "clone", "-q", str(repo), str(scratch))
    _configure(scratch)
    changes: list[tuple[str, str]] = []
    for i in range(FILES):
        if i % 2:
            (scratch / _name(i)).unlink()
            changes.append(("D", _name(i)))
        else:
            (scratch / _name(i)).write_text(f"x = {i + 1}\n", encoding="utf-8")
            changes.append(("M", _name(i)))
        (scratch / _name(FILES + i)).write_text("new = True\n", encoding="utf-8")
        changes.append(("A", _name(FILES + i)))
    _git(scratch, "add", "-A")
    _git(scratch, "commit", "-qm", "the change")
    _git(repo, "fetch", "-q", str(scratch), "dev")
    commit = _git(repo, "rev-parse", "FETCH_HEAD").strip()
    return repo, parent, commit, changes


@pytest.fixture
def longest_command(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The length of every command line the checks start, as Windows would count it."""
    seen: list[int] = []
    real = subprocess.run

    def measure(args, *rest, **kwargs):
        seen.append(len(subprocess.list2cmdline([str(a) for a in args])))
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(checks.subprocess, "run", measure)
    return seen


def test_the_running_copy_is_checked_for_work_across_thousands_of_files(big_change, longest_command) -> None:
    repo, parent, _commit, changes = big_change
    assert sum(len(path) + 1 for _, path in changes) > WINDOWS_LIMIT  # one line could never hold them

    assert checks.blue_dirty(repo, parent, changes) == []
    (repo / _name(1198)).write_text("someone's work\n", encoding="utf-8")
    assert checks.blue_dirty(repo, parent, changes) == [_name(1198)]
    assert max(longest_command) < WINDOWS_LIMIT


def test_work_already_in_place_is_found_across_thousands_of_files(big_change, longest_command) -> None:
    repo, parent, commit, changes = big_change
    tree = _git(repo, "rev-parse", f"{commit}^{{tree}}").strip()
    (repo / _name(0)).write_text("x = 1\n", encoding="utf-8")  # exactly what the change lands there

    assert checks.already_in_running_copy(repo, parent, tree, changes) == frozenset({_name(0)})
    assert max(longest_command) < WINDOWS_LIMIT


def test_a_change_to_thousands_of_files_lands_whole(big_change, longest_command) -> None:
    repo, parent, commit, changes = big_change

    assert checks.land(repo, "dev", commit, parent, changes) == ""
    assert _git(repo, "rev-parse", "dev").strip() == commit
    assert (repo / _name(0)).read_text(encoding="utf-8") == "x = 1\n"
    assert not (repo / _name(1)).exists()
    assert (repo / _name(FILES * 2 - 1)).read_text(encoding="utf-8") == "new = True\n"
    assert _git(repo, "status", "--porcelain") == ""  # nothing staged, nothing left over
    assert max(longest_command) < WINDOWS_LIMIT
