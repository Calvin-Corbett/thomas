"""A finished run in a task-born project becomes a real commit.

Measured twice (P1): a task-born project's only commit was the empty
"Baseline: contents before Thomas opened this project", so when a later run
overwrote a finished deliverable, Keep/Revert could only offer the empty
baseline back -- the finished work was unrecoverable. After a run records
``ok=True`` with changed files, the working tree is now committed as a
snapshot (`Thomas run <run_id-prefix>: <reason>`), so the NEXT run's changes
drawer diffs against the finished work and Revert restores it.

User-picked projects are never snapshot-committed: their history belongs to
them, and the manual Checkpoint button remains their path.

Also pinned here (w2-code-picked-project): when Thomas starts writing its
bookkeeping into a PICKED project, it plants ``.thomas/.gitignore`` with ``*``
so the user's own ``git status`` never shows ``?? .thomas/`` noise.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import forge_code_git, forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_git import _run_git
from thomas.server.routes import evolve_agent_runtime


def _task_born_repo(tmp_path: Path, name: str = "repo") -> Path:
    """A repo exactly as ``project_for_new_task`` leaves one: baseline + stamp."""
    repo = tmp_path / name
    repo.mkdir()
    _run_git(repo, ["init", "--initial-branch=main"])
    _run_git(repo, ["config", "user.email", "test@example.com"])
    _run_git(repo, ["config", "user.name", "Forge Test"])
    _run_git(repo, ["config", "commit.gpgsign", "false"])
    _run_git(repo, ["commit", "--allow-empty", "-m", "Baseline: contents before Thomas opened this project"])
    marker = repo / ".thomas" / "created-for-one-task.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"created_by": "project_for_new_task"}\n', encoding="utf-8")
    return repo.resolve()


def _picked_repo(tmp_path: Path, name: str = "picked") -> Path:
    """A user's own repo: real history, no task-born stamp."""
    repo = tmp_path / name
    repo.mkdir()
    _run_git(repo, ["init", "--initial-branch=main"])
    _run_git(repo, ["config", "user.email", "user@example.com"])
    _run_git(repo, ["config", "user.name", "Real User"])
    _run_git(repo, ["config", "commit.gpgsign", "false"])
    (repo / "README.md").write_text("theirs\n", encoding="utf-8")
    _run_git(repo, ["add", "-A"])
    _run_git(repo, ["commit", "-m", "user's own work"])
    return repo.resolve()


def _head_subject(repo: Path) -> str:
    _rc, out, _err = _run_git(repo, ["log", "-1", "--format=%s"])
    return out.strip()


def _commit_count(repo: Path) -> int:
    _rc, out, _err = _run_git(repo, ["rev-list", "--count", "HEAD"])
    return int(out.strip() or 0)


def test_a_task_born_run_snapshot_commits_the_finished_work(tmp_path: Path) -> None:
    repo = _task_born_repo(tmp_path)
    (repo / "index.html").write_text("<h1>countdown</h1>", encoding="utf-8")

    result = forge_code_git.commit_run_snapshot(repo, run_id="run-abcdef123456", reason="1 file(s) changed")

    assert result["committed"] is True
    assert _head_subject(repo) == "Thomas run run-abcd: 1 file(s) changed"
    # The tree is clean afterwards, so the NEXT run's launch snapshot is empty
    # and its drawer diffs against THIS finished state (git diff vs HEAD).
    assert forge_code_git.changed_files(repo) == []
    # .thomas internals stay out of the snapshot.
    _rc, tracked, _err = _run_git(repo, ["ls-files"])
    assert ".thomas" not in tracked


def test_revert_on_the_turn_after_a_snapshot_restores_the_finished_deliverable(tmp_path: Path) -> None:
    """The P1 scenario: run 2 overwrites run 1's finished page. Revert must
    bring back run 1's page, not the empty baseline."""
    repo = _task_born_repo(tmp_path)
    (repo / "index.html").write_text("finished deliverable v1", encoding="utf-8")
    assert forge_code_git.commit_run_snapshot(repo, run_id="run-1111", reason="1 file(s) changed")["committed"]

    # Run 2 (e.g. mis-routed by queue affinity) clobbers the page.
    (repo / "index.html").write_text("run 2 overwrote everything", encoding="utf-8")
    assert forge_code_git.changed_files(repo) == ["index.html"]

    outcome = forge_code_git.revert_file(repo, "index.html")

    assert outcome["ok"] is True and outcome["clean"] is True
    assert (repo / "index.html").read_text(encoding="utf-8") == "finished deliverable v1"


def test_the_next_runs_drawer_sees_only_its_own_changes(tmp_path: Path) -> None:
    repo = _task_born_repo(tmp_path)
    (repo / "index.html").write_text("v1\n", encoding="utf-8")
    forge_code_git.commit_run_snapshot(repo, run_id="run-1111", reason="1 file(s) changed")

    snap = forge_code_git.snapshot(repo)  # taken at the next run's launch
    assert snap == {}
    (repo / "index.html").write_text("v2\n", encoding="utf-8")
    (repo / "app.js").write_text("new\n", encoding="utf-8")

    assert forge_code_git.project_delta_since(repo, snap) == ["app.js", "index.html"]
    diff = forge_code_git.unified_diff(repo, "index.html")
    assert "+v2" in diff and "-v1" in diff


def test_a_picked_project_is_never_snapshot_committed(tmp_path: Path) -> None:
    repo = _picked_repo(tmp_path)
    (repo / "styles.css").write_text("body{}", encoding="utf-8")
    before = _commit_count(repo)

    result = forge_code_git.commit_run_snapshot(repo, run_id="run-2222", reason="1 file(s) changed")

    assert result["committed"] is False
    assert _commit_count(repo) == before
    assert forge_code_git.changed_files(repo) == ["styles.css"]


def test_a_snapshot_that_cannot_commit_reports_instead_of_raising(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _task_born_repo(tmp_path)
    (repo / "index.html").write_text("work", encoding="utf-8")
    monkeypatch.setattr(forge_code_git, "_run_git", lambda *_a, **_k: (1, "", "simulated git outage"))

    result = forge_code_git.commit_run_snapshot(repo, run_id="run-3333", reason="1 file(s) changed")

    assert result["committed"] is False


class _EmptyStdout:
    async def readline(self) -> bytes:
        return b""


class _ExitedProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = _EmptyStdout()

    async def wait(self) -> int:
        return self.returncode


def _record(repo: Path, cid: str, transcript: Path, proc: Any, snap: dict[str, str]) -> dict[str, Any]:
    return asyncio.run(
        evolve_agent_runtime._drain_and_record(
            proc,
            transcript,
            repo,
            cid,
            "test-model",
            snap,
            web.Application(),
            run_id="run-snapshot-wiring-1",
        )
    )


def test_drain_and_record_snapshots_a_successful_task_born_run(tmp_path: Path) -> None:
    repo = _task_born_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    snap = forge_code_git.snapshot(repo)
    (repo / "index.html").write_text("<h1>built</h1>", encoding="utf-8")
    transcript = tmp_path / "transcript.txt"
    transcript.write_text('{"fc":"say","text":"building"}\n', encoding="utf-8")

    result = _record(repo, conversation["id"], transcript, _ExitedProcess(0), snap)

    assert result["ok"] is True and result["outcome"] == "completed"
    assert forge_code_git.changed_files(repo) == []
    assert _head_subject(repo).startswith("Thomas run run-snap")


def test_drain_and_record_never_lets_a_snapshot_error_change_the_outcome(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _task_born_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    snap = forge_code_git.snapshot(repo)
    (repo / "index.html").write_text("<h1>built</h1>", encoding="utf-8")
    transcript = tmp_path / "transcript.txt"
    transcript.write_text('{"fc":"say","text":"building"}\n', encoding="utf-8")

    def _boom(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        raise RuntimeError("snapshot machinery broke")

    monkeypatch.setattr(forge_code_git, "commit_run_snapshot", _boom)

    result = _record(repo, conversation["id"], transcript, _ExitedProcess(0), snap)

    assert result["ok"] is True
    assert result["outcome"] == "completed"
    assert result["persistence_confirmed"] is True


def test_drain_and_record_leaves_a_picked_projects_history_alone(tmp_path: Path) -> None:
    repo = _picked_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    snap = forge_code_git.snapshot(repo)
    (repo / "styles.css").write_text("body{color:sienna}", encoding="utf-8")
    transcript = tmp_path / "transcript.txt"
    transcript.write_text('{"fc":"say","text":"styling"}\n', encoding="utf-8")
    before = _commit_count(repo)

    result = _record(repo, conversation["id"], transcript, _ExitedProcess(0), snap)

    assert result["ok"] is True and result["outcome"] == "completed"
    assert _commit_count(repo) == before
    assert "styles.css" in forge_code_git.changed_files(repo)
    assert _head_subject(repo) == "user's own work"


def test_binding_a_picked_project_shields_thomas_bookkeeping_from_their_git_status(tmp_path: Path) -> None:
    """w2-code-picked-project: after a Code run in the user's own repo, THEIR
    `git status` showed `?? .thomas/` forever. Binding now plants
    `.thomas/.gitignore` containing `*` so the noise never appears."""
    catalog = _picked_repo(tmp_path, "catalog")
    project = _picked_repo(tmp_path, "project")

    forge_code_projects.bind_conversation(catalog, "conv-shield", project)

    ignore = project / ".thomas" / ".gitignore"
    assert ignore.is_file()
    assert ignore.read_text(encoding="utf-8").strip() == "*"

    # Thomas writes its bookkeeping; the user's status stays silent about it.
    bookkeeping = project / ".thomas" / "evolve" / "agent" / "conversations" / "conv-shield.json"
    bookkeeping.parent.mkdir(parents=True)
    bookkeeping.write_text("{}", encoding="utf-8")
    _rc, out, _err = _run_git(project, ["status", "--porcelain"])
    assert ".thomas" not in out


def test_shielding_never_overwrites_an_existing_gitignore(tmp_path: Path) -> None:
    catalog = _picked_repo(tmp_path, "catalog")
    project = _picked_repo(tmp_path, "project")
    custom = project / ".thomas" / ".gitignore"
    custom.parent.mkdir(parents=True)
    custom.write_text("# user tuned this\nscratch/\n", encoding="utf-8")

    forge_code_projects.bind_conversation(catalog, "conv-keep", project)

    assert custom.read_text(encoding="utf-8") == "# user tuned this\nscratch/\n"


def test_a_task_born_project_is_born_shielded(tmp_path: Path, monkeypatch: Any) -> None:
    """The stamp dir doubles as the shield: a task-born project's .thomas
    noise never reaches its own status output either."""
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")

    project = forge_code_projects.project_for_new_task("Make a countdown page")

    assert (project / ".thomas" / ".gitignore").is_file()
    _rc, out, _err = _run_git(project, ["status", "--porcelain"])
    assert ".thomas" not in out
