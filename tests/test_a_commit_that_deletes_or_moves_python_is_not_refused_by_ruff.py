"""A commit that deletes or moves a Python file must not be refused by the ruff gates.

The scoped commit path hands ruff the Python files of the commit scope. A deleted file and the old name of a moved file are in
that scope (git lists them) but not on disk, and `ruff check` answers E902 file not found for each: a refusal no action
satisfies. The fix keeps only the paths that still exist. These tests stage a real deletion and a real rename in a throwaway
repository and run the command the gate would run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(_REPO))
from scripts.crew.brief import commit as commit_tool  # noqa: E402


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return done.stdout


@pytest.fixture()
def staged_repo(tmp_path: Path) -> tuple[Path, list[str]]:
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _git(tmp_path, *args)
    for name in ("gone.py", "moved.py", "stays.py"):
        (tmp_path / name).write_text(f'"""{name}."""\n\nVALUE = 1\n', encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "rm", "-q", "gone.py")  # a deletion
    _git(tmp_path, "mv", "moved.py", "renamed.py")  # a rename: old name gone, new name present
    (tmp_path / "stays.py").write_text('"""stays.py."""\n\nVALUE = 2\n', encoding="utf-8")  # an ordinary edit
    _git(tmp_path, "add", "-A")
    selected = _git(tmp_path, "diff", "--cached", "--name-only", "--no-renames").split()
    assert sorted(selected) == ["gone.py", "moved.py", "renamed.py", "stays.py"]
    return tmp_path, selected


def _ruff_tail(command: list[str]) -> list[str]:
    """The `-m ruff ...` part of a gate command, runnable with this interpreter in the throwaway repo."""
    return [sys.executable, "-m", *command[command.index("ruff") :]]


@pytest.mark.parametrize("gate_name", ["ruff", "ruff_format"])
def test_ruff_is_only_given_paths_that_exist(
    staged_repo: tuple[Path, list[str]], monkeypatch: pytest.MonkeyPatch, gate_name: str
) -> None:
    root, selected = staged_repo
    monkeypatch.setattr(commit_tool, "_REPO_ROOT", root)
    registry = dict(commit_tool.LOCAL_GATE_COMMANDS)

    assert commit_tool._gate_applies(gate_name, selected)
    command = commit_tool._resolved_gate_command(gate_name, registry[gate_name], selected_paths=selected)
    paths = [part for part in command if part.endswith(".py") and "/" not in part and "\\" not in part]

    assert sorted(paths) == ["renamed.py", "stays.py"], (
        "the deleted file and the old name of the move must not reach ruff"
    )
    done = subprocess.run(_ruff_tail(command), cwd=root, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_old_behaviour_would_have_failed_here(staged_repo: tuple[Path, list[str]]) -> None:
    """Control: handing ruff every selected path, as the gate did before the fix, is E902 on the deleted file."""
    root, selected = staged_repo

    done = subprocess.run([sys.executable, "-m", "ruff", "check", *selected], cwd=root, capture_output=True, text=True)

    assert done.returncode != 0
    assert "gone.py" in done.stdout + done.stderr


def test_a_commit_that_only_deletes_python_runs_no_ruff_at_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commit_tool, "_REPO_ROOT", tmp_path)

    assert not commit_tool._gate_applies("ruff", ["removed_module.py", "docs/note.md"])
    assert not commit_tool._gate_applies("ruff_format", ["removed_module.py"])
