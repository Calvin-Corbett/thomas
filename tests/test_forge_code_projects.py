from __future__ import annotations

from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_projects, forge_code_tree
from thomas.forge.anvil.forge_code_git import _run_git


def _repo(path: Path) -> Path:
    path.mkdir()
    _run_git(path, ["init"])
    return path.resolve()


def test_project_selection_resolves_git_root_and_persists_per_conversation(tmp_path: Path) -> None:
    catalog = _repo(tmp_path / "catalog")
    project = _repo(tmp_path / "project")
    nested = project / "src"
    nested.mkdir()

    assert forge_code_projects.validate_project_root(nested, fallback=catalog) == project
    settings = {"effective": {"model": "gpt-5.6-codex"}}
    forge_code_projects.bind_conversation(catalog, "conv-1", nested, settings=settings)

    assert forge_code_projects.conversation_project(catalog, "conv-1") == project
    assert forge_code_projects.conversation_metadata(catalog, "conv-1") == {
        "project_root": str(project),
        "settings": settings,
    }
    assert set(forge_code_projects.conversation_roots(catalog)) == {catalog, project}


def test_project_selection_rejects_relative_missing_and_non_repo_paths(tmp_path: Path) -> None:
    catalog = _repo(tmp_path / "catalog")
    plain = tmp_path / "plain"
    plain.mkdir()

    for invalid in (Path("relative"), tmp_path / "missing", plain):
        with pytest.raises(forge_code_projects.ForgeCodeProjectError):
            forge_code_projects.validate_project_root(invalid, fallback=catalog)


def test_tree_is_scoped_metadata_only_and_hides_internal_directories(tmp_path: Path) -> None:
    project = _repo(tmp_path / "project")
    (project / ".thomas").mkdir()
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("raise SystemExit\n", encoding="utf-8")
    (project / "README.md").write_text("private contents\n", encoding="utf-8")

    root = forge_code_tree.list_project_tree(project)
    by_name = {entry["name"]: entry for entry in root["entries"]}
    assert set(by_name) == {"README.md", "src"}
    assert by_name["README.md"] == {
        "name": "README.md",
        "path": "README.md",
        "kind": "file",
        "size": (project / "README.md").stat().st_size,
    }
    assert "private contents" not in str(root)

    nested = forge_code_tree.list_project_tree(project, "src")
    assert [entry["path"] for entry in nested["entries"]] == ["src/app.py"]
    with pytest.raises(forge_code_tree.ForgeCodeTreeError):
        forge_code_tree.list_project_tree(project, "../outside")
