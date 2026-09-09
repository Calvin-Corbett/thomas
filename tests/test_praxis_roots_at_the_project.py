from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

BOARD_SECTIONS = (
    "## Execution Status",
    "## Problem Traceability",
    "## Agent Claims",
    "## Active Tasks",
    "## Up For Grabs",
    "## Issues / Blockers",
    "## Task Problems",
    "## Agent Message Traffic",
    "## Task Plans",
    "## Inactive Agents",
)
EXISTING_LINE = "- task_id=keep-me; scope=chat; summary=existing"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A throwaway git project that is not the Thomas checkout."""
    root = tmp_path / "someones-app"
    (root / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_project_root_is_the_nearest_git_ancestor_not_the_thomas_checkout(project: Path) -> None:
    from thomas.core.project_root import resolve_project_root

    assert resolve_project_root(project / "src") == project.resolve()


def test_explicit_env_root_wins(project: Path, monkeypatch) -> None:
    from thomas.core.project_root import resolve_project_root

    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(project))
    assert resolve_project_root(Path.cwd()) == project.resolve()


def test_ensure_praxis_scaffolds_a_board_and_coordination_dir_once(project: Path) -> None:
    from thomas.core.praxis_scaffold import ensure_praxis

    paths = ensure_praxis(project)
    assert paths.board == project / "plans" / "someones-app" / "WORKBOARD.md"
    assert paths.coordination_dir == project / "runtime" / "coordination"
    assert paths.coordination_dir.is_dir()
    text = paths.board.read_text(encoding="utf-8")
    for section in BOARD_SECTIONS:
        assert section in text, section
    assert "- none" in text  # Up For Grabs starts empty, the way the dispatcher expects

    paths.board.write_text(text + EXISTING_LINE + "\n", encoding="utf-8")
    again = ensure_praxis(project)  # idempotent: never overwrites a board that exists
    assert "keep-me" in again.board.read_text(encoding="utf-8")


def test_dispatch_writes_to_the_projects_own_board_not_thomass(project: Path) -> None:
    """Integration: wired after the hub call sites change (plan steps 4-5)."""
    from thomas.agent import chat_dispatcher

    thomas_board = chat_dispatcher._DEFAULT_WORKBOARD
    before = thomas_board.read_bytes() if thomas_board.exists() else None

    ok = chat_dispatcher._add_task_to_workboard("t-1", "do a thing", repo_root=project)

    assert ok is True
    board = project / "plans" / "someones-app" / "WORKBOARD.md"
    assert board.exists() and "t-1" in board.read_text(encoding="utf-8")
    after = thomas_board.read_bytes() if thomas_board.exists() else None
    assert before == after, "Thomas's own board must be untouched by a foreign project's task"


def test_dispatch_to_workboard_end_to_end_uses_the_projects_board(project: Path, monkeypatch) -> None:
    """The production path: dispatch_to_workboard -> _add_task_to_workboard -> the project's board."""
    from thomas.agent import chat_dispatcher
    from thomas.core import task_bot_runtime

    monkeypatch.setattr(chat_dispatcher, "_notify_task_manager", lambda *a, **k: True, raising=False)
    result = chat_dispatcher.dispatch_to_workboard("build the thing", "sess-1", repo_root=project)
    board = project / "plans" / "someones-app" / "WORKBOARD.md"
    assert board.exists(), result
    assert result.task_id in board.read_text(encoding="utf-8")
    # the execution record lands in the project too, not in Thomas's own runtime dir
    assert list((project / "runtime" / "coordination").rglob("*.json")), "no execution written under the project"


def test_task_bot_runtime_coordination_dir_follows_the_project(project: Path, monkeypatch) -> None:
    from thomas.core import task_bot_runtime

    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(project))
    assert task_bot_runtime.coordination_dir() == project.resolve() / "runtime" / "coordination"
    assert task_bot_runtime.coordination_dir(project / "src") == (project / "src").resolve() / "runtime" / "coordination"


def test_a_folder_inside_the_data_dir_roots_at_the_data_dir_not_home(tmp_path: Path, monkeypatch) -> None:
    """A one-off job (a PDF, a note) works in ~/.thomas/workspaces/<id>; its board is the
    user's own board in the data dir, never a walk up to the home directory."""
    from thomas.core.project_root import resolve_project_root, user_praxis_root

    data = tmp_path / "ThomasData"
    job = data / "workspaces" / "exec-42"
    job.mkdir(parents=True)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))
    monkeypatch.delenv("THOMAS_PROJECT_ROOT", raising=False)
    assert resolve_project_root(job) == data.resolve()
    assert user_praxis_root() == data.resolve()


def test_a_plain_folder_with_no_repo_is_its_own_root(tmp_path: Path, monkeypatch) -> None:
    from thomas.core.project_root import resolve_project_root

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.delenv("THOMAS_PROJECT_ROOT", raising=False)
    folder = tmp_path / "Documents" / "thing"
    folder.mkdir(parents=True)
    assert resolve_project_root(folder) == folder.resolve()


def test_coordination_root_sends_one_offs_to_the_users_board(project: Path, tmp_path: Path, monkeypatch) -> None:
    from thomas.core.project_root import coordination_root

    data = tmp_path / "ThomasData"
    data.mkdir()
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))
    monkeypatch.delenv("THOMAS_PROJECT_ROOT", raising=False)
    assert coordination_root(project, "project") == project.resolve()
    assert coordination_root(None, "isolated") == data.resolve()
    assert coordination_root(project, "isolated") == data.resolve()
