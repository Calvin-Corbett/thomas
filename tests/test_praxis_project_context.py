"""Chat can select an actual Build project without inventing a root."""

from pathlib import Path

from thomas.server.praxis import project_context


def test_relevant_existing_project_is_shown_with_exact_dispatch_id(tmp_path, monkeypatch):
    source = tmp_path / "Thomas"
    projects = [tmp_path / "Unrelated"] + [tmp_path / f"Scratch {n}" for n in range(40)]
    game = tmp_path / "Minecraft World"
    projects.append(game)
    monkeypatch.setattr(project_context, "_default_repo_root", lambda: source)
    monkeypatch.setattr(project_context.forge_code_projects, "conversation_roots", lambda _: [source, *projects])
    monkeypatch.setattr(project_context.forge_code_projects, "thomas_source_repo_root", lambda: source)

    context = project_context.build_project_catalog_context("Continue the Minecraft World game")

    assert '"id": "' + str(game).replace("\\", "\\\\") + '"' in context
    assert str(source) not in context
    assert "Showing 32 of 42" in context


def test_unrelated_chat_turn_does_not_spend_tokens_on_project_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(project_context, "_default_repo_root", lambda: tmp_path)
    monkeypatch.setattr(project_context.forge_code_projects, "conversation_roots", lambda _: [])
    monkeypatch.setattr(project_context.forge_code_projects, "thomas_source_repo_root", lambda: None)
    assert project_context.build_project_catalog_context("Build a new game") == ""


def test_thomas_source_request_does_not_offer_unrelated_build_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(project_context, "_default_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        project_context.forge_code_projects, "conversation_roots", lambda _: [tmp_path / "Life Manager"]
    )
    assert project_context.build_project_catalog_context("Edit Life Manager inside the Thomas repo") == ""
