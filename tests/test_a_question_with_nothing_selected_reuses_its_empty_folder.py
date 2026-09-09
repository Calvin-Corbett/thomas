"""A question asked with nothing selected must stop minting sibling junk folders.

Measured live (3x, 2026-08-05): asking Code "look at the project I have
selected..." with no project selected mints a brand-new empty git-initialized
folder named after the sentence -- "Look at the project I have selected tell
me what 3", with siblings 1 and 2 already there. Every repeat of the question
added another empty folder to ~/.thomas/projects.

The fix is reuse, not deletion: the conversation transcript lives INSIDE the
minted folder (<project>/.thomas/evolve/agent/conversations/<cid>.json), so
removing the folder would destroy the answer, and rebinding the record
elsewhere would point a follow-up run at whatever root it was rebound to.
Instead, when a run finishes as a pure answer (outcome "conversation") in a
task-born folder that holds nothing but .git and .thomas internals, the folder
is marked free for another question -- and the NEXT question with the same
name claims it instead of minting sibling 3, 4, 5.

Nothing here is a gate: an unmarked folder simply means the next question
mints its own folder, exactly as before. A folder that gained files is never
reused. A user's own folder is never marked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import forge_code_git, forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_git import _run_git
from thomas.server.routes import evolve_agent_runtime

SENTENCE = "Look at the project I have selected tell me what it does"


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
            run_id="run-junk-folder-reuse-1",
        )
    )


def _answer_only_run(repo: Path, tmp_path: Path) -> dict[str, Any]:
    """Drive a real _drain_and_record whose evidence says: answered, no files."""
    conversation = forge_code_store.new_conversation(repo)
    snap = forge_code_git.snapshot(repo)
    transcript = tmp_path / f"transcript-{conversation['id']}.txt"
    transcript.write_text('{"fc":"final","text":"No project is selected; this folder is empty."}\n', encoding="utf-8")
    return _record(repo, conversation["id"], transcript, _ExitedProcess(0), snap)


def _picked_repo(tmp_path: Path, name: str = "picked") -> Path:
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


def test_an_answer_only_run_frees_its_folder_and_the_next_question_reuses_it(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")

    first = forge_code_projects.project_for_new_task(SENTENCE)
    result = _answer_only_run(first, tmp_path)
    assert result["outcome"] == "conversation"

    second = forge_code_projects.project_for_new_task(SENTENCE)

    assert second == first
    siblings = [p.name for p in (tmp_path / ".thomas" / "projects").iterdir()]
    assert len(siblings) == 1, f"a sibling junk folder was minted: {siblings}"


def test_the_answer_survives_reuse(tmp_path: Path, monkeypatch: Any) -> None:
    """Preserving the transcript outranks tidiness: reuse must never delete
    the previous question's conversation record."""
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")

    first = forge_code_projects.project_for_new_task(SENTENCE)
    result = _answer_only_run(first, tmp_path)
    assert result["outcome"] == "conversation"
    recorded = list((first / ".thomas" / "evolve" / "agent" / "conversations").glob("*.json"))
    assert recorded, "the answer-only run left no conversation record"

    second = forge_code_projects.project_for_new_task(SENTENCE)

    assert second == first
    for record in recorded:
        assert record.is_file(), f"reuse destroyed the transcript {record.name}"


def test_a_folder_whose_run_is_still_unfinished_is_not_reused(tmp_path: Path, monkeypatch: Any) -> None:
    """No finished answer-only run, no reuse: two same-named tasks in flight
    still get separate folders (the shared-drawer defect must not return)."""
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")

    first = forge_code_projects.project_for_new_task(SENTENCE)
    second = forge_code_projects.project_for_new_task(SENTENCE)

    assert second != first


def test_a_folder_that_gained_files_is_never_freed_or_reused(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")

    first = forge_code_projects.project_for_new_task(SENTENCE)
    (first / "index.html").write_text("<h1>real work</h1>", encoding="utf-8")

    assert forge_code_projects.mark_workspace_reusable(first) is False
    second = forge_code_projects.project_for_new_task(SENTENCE)

    assert second != first


def test_a_build_run_does_not_free_its_folder(tmp_path: Path, monkeypatch: Any) -> None:
    """A run that changed files finished as work, not as a question -- its
    folder holds a deliverable and must keep its own identity."""
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")

    first = forge_code_projects.project_for_new_task(SENTENCE)
    conversation = forge_code_store.new_conversation(first)
    snap = forge_code_git.snapshot(first)
    (first / "index.html").write_text("<h1>built</h1>", encoding="utf-8")
    transcript = tmp_path / "transcript-build.txt"
    transcript.write_text('{"fc":"say","text":"building"}\n', encoding="utf-8")

    result = _record(first, conversation["id"], transcript, _ExitedProcess(0), snap)
    assert result["outcome"] == "completed"

    second = forge_code_projects.project_for_new_task(SENTENCE)
    assert second != first


def test_reuse_is_claimed_once_per_finished_answer(tmp_path: Path, monkeypatch: Any) -> None:
    """The claim is consumed on reuse, so a third question arriving while the
    second still runs gets its own folder rather than sharing mid-flight."""
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")

    first = forge_code_projects.project_for_new_task(SENTENCE)
    assert forge_code_projects.mark_workspace_reusable(first) is True

    second = forge_code_projects.project_for_new_task(SENTENCE)
    third = forge_code_projects.project_for_new_task(SENTENCE)

    assert second == first
    assert third != first


def test_a_differently_named_question_keeps_its_own_folder_name(tmp_path: Path, monkeypatch: Any) -> None:
    """The folder name is what the chip shows; a different question must not
    inherit a folder named after someone else's sentence."""
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")

    first = forge_code_projects.project_for_new_task(SENTENCE)
    assert forge_code_projects.mark_workspace_reusable(first) is True

    other = forge_code_projects.project_for_new_task("What time is it in Tokyo")

    assert other != first


def test_a_users_own_folder_is_never_marked_reusable(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")
    picked = _picked_repo(tmp_path)

    assert forge_code_projects.mark_workspace_reusable(picked) is False

    result = _answer_only_run(picked, tmp_path)
    assert result["outcome"] == "conversation"
    # Even after an answer-only run inside it, a picked folder carries no
    # reuse marker: it is theirs, not a mint to recycle.
    assert not (picked / ".thomas" / "free-for-another-question.json").exists()
