"""A commit message reaches git as the bytes it was written with.

Every tool that makes a commit by plumbing hands the message to ``git commit-tree``
on stdin. Text mode on Windows writes that pipe as cp1252 and turns each ``\\n`` into
``\\r\\n``. So every commit b4f33dee's tool made carried a CR on each line (42 in that
one), a message written to a file on Windows failed the integrity check as
``broken_repo_tool``, and a single "→" crashed the commit with a charmap error.
The read-back hid the CRs because it ran in text mode too.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from scripts.cage import self_change_checks
from scripts.crew.brief import commit as scoped
from scripts.crew.brief import commit_integrity
from scripts.forge import commit_master

WRITTEN = "fix: the arrow → survives, and so does é\n\nsecond paragraph\n"


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Thomas Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")  # the owner's global config signs
    (tmp_path / "a.txt").write_bytes(b"one\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


RUNNERS: dict[str, Callable[[Path, list[str], str], subprocess.CompletedProcess[str]]] = {
    "commit.py": lambda repo, args, text: scoped._run_git(repo, args, input_text=text),
    "commit_master": lambda repo, args, text: commit_master._git(repo, *args, input_text=text),
    "self-change promoter": lambda repo, args, text: self_change_checks.run_git(repo, *args, stdin=text),
}


@pytest.mark.parametrize("name", sorted(RUNNERS))
def test_every_plumbing_runner_hands_git_utf8_with_lf(repo: Path, name: str) -> None:
    made = RUNNERS[name](repo, ["hash-object", "-w", "--stdin"], WRITTEN)
    assert made.returncode == 0, made.stderr
    stored = _git(repo, "cat-file", "blob", made.stdout.strip())
    assert stored == WRITTEN.encode("utf-8"), name


def test_a_crlf_message_is_the_same_message() -> None:
    assert commit_integrity.validate_caller_message("fix: x\r\n\r\nbody\r\n") == "fix: x\n\nbody"


def test_the_scoped_tool_commits_a_windows_written_message_intact(repo: Path) -> None:
    trailers = [("Thomas-Agent", "claude"), ("Thomas-Scope", "a.txt")]
    from_a_windows_file = WRITTEN.replace("\n", "\r\n")
    index = repo / "scoped-index"
    parent = _git(repo, "rev-parse", "HEAD").decode().strip()
    scoped._git_output(repo, ["read-tree", "HEAD"], env=scoped._temp_index_env("claude", index))

    sha = scoped._create_commit_object(
        repo,
        agent="claude",
        index_path=index,
        parent_head=parent,
        message=commit_integrity.compose_message(from_a_windows_file, trailers),
        expected_body=from_a_windows_file,
        expected_trailers=trailers,
    )

    raw = _git(repo, "cat-file", "commit", sha)
    assert b"\r" not in raw
    assert "the arrow → survives, and so does é".encode() in raw
