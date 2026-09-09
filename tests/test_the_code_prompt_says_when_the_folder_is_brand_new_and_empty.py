"""SIGHT: the composed Code prompt names reality when the workspace was minted
for this very task.

Measured live: asking "look at the project I have selected..." with nothing
selected mints a fresh empty folder, and the model -- told nothing about where
it is standing -- answers as if that empty folder were the user's chosen
project. The prompt now says plainly, when (and only when) the working folder
is a task-born mint that still holds nothing but .git and .thomas internals:
this is a brand-new empty folder created for this task, nothing is selected.

This is sight, not a gate: nothing filters, rejects, or reshapes the model's
answer, and nothing restricts what it may do in the folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_projects
from thomas.forge.anvil.bridge_prompts import compose_headless_prompt
from thomas.forge.anvil.forge_code_git import _run_git

QUESTION = "look at the project I have selected tell me what it does"


def _minted(tmp_path: Path, monkeypatch: Any) -> Path:
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: tmp_path / ".thomas")
    return forge_code_projects.project_for_new_task(QUESTION)


def test_a_fresh_task_born_folder_is_named_for_what_it_is(tmp_path: Path, monkeypatch: Any) -> None:
    project = _minted(tmp_path, monkeypatch)

    prompt = compose_headless_prompt(QUESTION, project_root=project)

    assert "brand-new empty folder created for this task" in prompt
    assert "nothing is selected" in prompt


def test_a_task_born_folder_with_real_work_gets_no_empty_folder_note(tmp_path: Path, monkeypatch: Any) -> None:
    project = _minted(tmp_path, monkeypatch)
    (project / "index.html").write_text("<h1>built earlier</h1>", encoding="utf-8")

    prompt = compose_headless_prompt("what did you build?", project_root=project)

    assert "brand-new empty folder" not in prompt


def test_a_users_own_folder_gets_no_empty_folder_note(tmp_path: Path) -> None:
    picked = tmp_path / "their-project"
    picked.mkdir()
    _run_git(picked, ["init", "--initial-branch=main"])

    prompt = compose_headless_prompt(QUESTION, project_root=picked)

    assert "brand-new empty folder" not in prompt


def test_no_project_root_means_no_note_and_no_error(tmp_path: Path) -> None:
    prompt = compose_headless_prompt(QUESTION)

    assert "brand-new empty folder" not in prompt
    assert "## User" in prompt
