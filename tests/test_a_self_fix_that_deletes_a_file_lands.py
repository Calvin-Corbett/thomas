"""A self-fix that deletes a file lands, and one that cannot land leaves nothing staged behind.

On 2026-09-25 the junk sweep you asked for was the first Thomas project to delete files (with the delete tool that
had just reached his teams), and you approved its card. The promoter moved ``dev``, then ran ``git rm`` on the
deleted files in the running copy -- but HEAD already pointed at the new commit, where those files are gone, so git
saw each index entry as a staged change and refused ("the following files have changes staged in the index"). The
rollback ran the same ``git rm`` on the files the change added, failed the same way, and left the change's new
changelog fragment staged in your checkout. ``land`` only runs after ``blue_dirty`` found no uncommitted work in any
of these paths, so removing them outright is safe.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks

from tests.sleep_support import skip_sleeps


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def running_copy(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "running"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "dev")
    for key, value in (
        ("user.name", "Thomas Test"),
        ("user.email", "test@example.invalid"),
        ("commit.gpgsign", "false"),
    ):
        _git(repo, "config", key, value)
    (repo / "kept.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "junk.py").write_text("dead = True\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    parent = _git(repo, "rev-parse", "HEAD").strip()
    # The approved change, made the promoter's way: a commit object dev does not point at yet.
    scratch = tmp_path / "scratch"
    _git(tmp_path, "clone", "-q", str(repo), str(scratch))
    for key, value in (
        ("user.name", "Thomas Test"),
        ("user.email", "test@example.invalid"),
        ("commit.gpgsign", "false"),
    ):
        _git(scratch, "config", key, value)
    (scratch / "kept.py").write_text("x = 2\n", encoding="utf-8")
    (scratch / "junk.py").unlink()
    (scratch / "notes.md").write_text("gone\n", encoding="utf-8")
    _git(scratch, "add", "-A")
    _git(scratch, "commit", "-qm", "the change")
    _git(repo, "fetch", "-q", str(scratch), "dev")
    commit = _git(repo, "rev-parse", "FETCH_HEAD").strip()
    return repo, parent, commit


CHANGES = [("M", "kept.py"), ("D", "junk.py"), ("A", "notes.md")]


def test_a_change_that_deletes_a_file_lands_in_the_running_copy(running_copy) -> None:
    repo, parent, commit = running_copy
    assert checks.land(repo, "dev", commit, parent, CHANGES) == ""
    assert _git(repo, "rev-parse", "dev").strip() == commit
    assert not (repo / "junk.py").exists()
    assert (repo / "notes.md").read_text(encoding="utf-8") == "gone\n"
    assert (repo / "kept.py").read_text(encoding="utf-8") == "x = 2\n"
    assert _git(repo, "status", "--porcelain") == ""  # nothing staged, nothing left over


def test_a_landing_that_fails_puts_everything_back_with_nothing_staged(running_copy, monkeypatch) -> None:
    repo, parent, commit = running_copy
    real = checks.run_git

    def refuse_removing_the_deleted_file(where, *args, **kwargs):
        # What happened on 2026-09-25: the kept and added files were checked out (and staged), then the removal
        # failed. The rollback must still leave nothing staged.
        if args and args[0] == "rm" and "junk.py" in args:
            return subprocess.CompletedProcess(["git", *args], 1, "", "error: simulated")
        return real(where, *args, **kwargs)

    monkeypatch.setattr(checks, "run_git", refuse_removing_the_deleted_file)
    skip_sleeps(monkeypatch)
    with pytest.raises(checks.Refused, match="dev was put back"):
        checks.land(repo, "dev", commit, parent, CHANGES)
    assert _git(repo, "rev-parse", "dev").strip() == parent
    assert (repo / "junk.py").read_text(encoding="utf-8") == "dead = True\n"
    assert not (repo / "notes.md").exists()
    assert _git(repo, "status", "--porcelain") == ""
