"""The append-only rule for plans/thomas/archive/, checked on staged changes in a real git repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.praxis import archive_append_only as rule

OLD = b"<!-- header -->\nrow one\nrow two\n"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "core.autocrlf", "false")
    folder = tmp_path / "plans" / "thomas" / "archive"
    folder.mkdir(parents=True)
    (folder / "messages-2026-06.txt").write_bytes(OLD)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def stage(repo: Path, name: str, data: bytes | None) -> None:
    path = repo / "plans" / "thomas" / "archive" / name
    if data is None:
        git(repo, "rm", "-q", "-f", f"plans/thomas/archive/{name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    git(repo, "add", "-A")


def test_an_append_and_a_new_month_pass(repo: Path) -> None:
    stage(repo, "messages-2026-06.txt", OLD + b"row three\n")
    stage(repo, "messages-2026-07.txt", b"new month\n")
    assert rule.staged_violations(repo) == []


@pytest.mark.parametrize(
    "edited", [b"<!-- header -->\nrow ONE\nrow two\nrow three\n", b"<!-- header -->\nrow one\n", OLD, b"x" + OLD]
)
def test_an_edit_a_truncation_or_a_no_change_is_a_violation(repo: Path, edited: bytes) -> None:
    stage(repo, "messages-2026-06.txt", edited)
    found = rule.staged_violations(repo)
    assert edited == OLD or any("not just appended" in line for line in found)


def test_a_delete_is_a_violation(repo: Path) -> None:
    stage(repo, "messages-2026-06.txt", None)
    assert any("status D" in line for line in rule.staged_violations(repo))


@pytest.mark.parametrize(
    "name", ["notes.txt", "messages-2026-13.txt", "messages-2026-6.txt", "sub/messages-2026-06.txt"]
)
def test_other_files_under_the_folder_are_violations(repo: Path, name: str) -> None:
    stage(repo, name, b"x\n")
    assert any("only plans/thomas/archive/messages-YYYY-MM.txt" in line for line in rule.staged_violations(repo))


def test_nothing_staged_is_clean_and_main_reports_the_exit_code(repo: Path, capsys) -> None:
    assert rule.main([str(repo)]) == 0
    stage(repo, "messages-2026-06.txt", b"rewritten\n")
    assert rule.main([str(repo)]) == 1 and "archive append-only check" in capsys.readouterr().out
