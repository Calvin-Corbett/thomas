"""The direct-agent finish path cannot declare work done with dirty claimed files."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.crew.brief import commit, task_closure


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    (tmp_path / "owned.txt").write_text("base", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "owned.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    return tmp_path


def _committed_result() -> commit.CommitResult:
    return commit.CommitResult(
        ok=True,
        blocker_class=None,
        message="committed",
        agent="test-agent",
        branch="main",
        claim_scopes=("owned.txt",),
        selected_paths=("owned.txt",),
        commit_sha="a" * 40,
    )


def test_remaining_claimed_edit_holds_done_and_release(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "owned.txt").write_text("still dirty", encoding="utf-8")
    monkeypatch.setattr(task_closure.commit, "commit_scoped_changes", lambda **_kwargs: _committed_result())
    monkeypatch.setattr(
        task_closure.manager,
        "set_task_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not set done")),
    )
    result = task_closure.finish_claimed_task(
        agent="test-agent", task_id="TASK", message="finish", repo_root=repo, workboard_path=repo / "board.md"
    )
    assert result.stage == "remaining_work"
    assert result.remaining_paths == ("owned.txt",)


def test_unrelated_dirty_file_does_not_contaminate_claim(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "another-agent.txt").write_text("untouched", encoding="utf-8")
    monkeypatch.setattr(task_closure.commit, "commit_scoped_changes", lambda **_kwargs: _committed_result())
    transitions: list[str] = []

    def status(_board, **kwargs):
        transitions.append(kwargs["status"])
        return True, {}

    monkeypatch.setattr(task_closure.manager, "set_task_status", status)
    monkeypatch.setattr(task_closure.claim, "release", lambda *_args, **_kwargs: (True, "released"))
    result = task_closure.finish_claimed_task(
        agent="test-agent", task_id="TASK", message="finish", repo_root=repo, workboard_path=repo / "board.md"
    )
    assert result.ok
    assert transitions == ["review", "done"]
    assert (repo / "another-agent.txt").read_text(encoding="utf-8") == "untouched"


def test_failed_commit_cannot_mark_task_done(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    failed = commit.CommitResult(
        ok=False,
        blocker_class="gate_failed",
        message="gate rejected the change",
        agent="test-agent",
        branch="main",
        claim_scopes=("owned.txt",),
        selected_paths=("owned.txt",),
    )
    monkeypatch.setattr(task_closure.commit, "commit_scoped_changes", lambda **_kwargs: failed)
    monkeypatch.setattr(
        task_closure.manager,
        "set_task_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not set done")),
    )
    result = task_closure.finish_claimed_task(
        agent="test-agent", task_id="TASK", message="finish", repo_root=repo, workboard_path=repo / "board.md"
    )
    assert not result.ok
    assert result.stage == "commit"
    assert "gate rejected" in result.message
