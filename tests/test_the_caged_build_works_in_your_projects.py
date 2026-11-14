"""The caged Thomas builds in your projects, not in an empty copy under its own account.

Build roots its projects, scratch folder and task workspaces at ``~/.thomas``. The
caged server runs as the cage account, whose home is not yours, so its Build saw
none of your projects. ``THOMAS_OWNED_ROOT`` (set by scripts/cage/caged_server.py)
now names that root, and every one of those places follows it together -- a
project created there is still "Thomas-owned", so it is git-initialised and opens.
"""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil import forge_code_conversations, forge_code_projects
from thomas.server import chat_delegation_workspace


def test_every_build_folder_follows_the_owned_root(tmp_path: Path, monkeypatch) -> None:
    owner = tmp_path / "owner" / ".thomas"
    monkeypatch.setenv("THOMAS_OWNED_ROOT", str(owner))

    assert forge_code_projects.thomas_owned_root() == owner
    assert forge_code_projects.shared_scratch_root() == owner / "code_scratch"
    project = forge_code_projects.create_named_project("Snake Game")
    assert project.parent == owner / "projects"
    assert forge_code_projects.is_thomas_owned(project)
    assert (project / ".git").exists(), "a project made under the owned root must open in Build"
    assert chat_delegation_workspace.ensure_task_workspace("exec-abc").parent == owner / "workspaces"


def test_without_the_setting_it_is_still_your_home(monkeypatch) -> None:
    monkeypatch.delenv("THOMAS_OWNED_ROOT", raising=False)

    assert forge_code_projects.thomas_owned_root() == Path.home() / ".thomas"


def test_the_conversation_registry_still_answers_from_its_old_home(tmp_path: Path) -> None:
    for name in forge_code_conversations.NAMES:
        assert getattr(forge_code_projects, name) is getattr(forge_code_conversations, name)
    forge_code_projects._write_registry(tmp_path, {"c1": {"project_root": str(tmp_path)}})
    assert forge_code_projects.conversation_metadata(tmp_path, "c1") == {"project_root": str(tmp_path)}
