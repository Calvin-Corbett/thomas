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


def test_a_thomas_owned_folder_is_prepared_with_a_revertible_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything Thomas builds lands in a folder with no version history, so
    the 913 apps it had made were unopenable. Preparing one must also leave a
    baseline: Revert is `git checkout -- <file>`, which needs a commit to
    return to, or the first edit becomes permanent."""
    project = tmp_path / "workspaces" / "exec-abc123"
    project.mkdir(parents=True)
    (project / "app.html").write_text("original", encoding="utf-8")
    monkeypatch.setattr(forge_code_projects, "is_thomas_owned", lambda _path: True)

    assert forge_code_projects.ensure_git_repo(project) is True
    assert (project / ".git").exists()

    returncode, _stdout, _stderr = _run_git(project, ["rev-parse", "--verify", "HEAD"])
    assert returncode == 0, "a prepared project must have a baseline commit"

    (project / "app.html").write_text("edited by Thomas", encoding="utf-8")
    _run_git(project, ["checkout", "--", "app.html"])
    assert (project / "app.html").read_text(encoding="utf-8") == "original"


def test_a_users_own_folder_is_never_initialised_behind_their_back(tmp_path: Path) -> None:
    outside = tmp_path / "MyVacationPhotos"
    outside.mkdir()

    assert forge_code_projects.ensure_git_repo(outside) is False
    assert not (outside / ".git").exists()


def test_preparing_an_already_prepared_project_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _repo(tmp_path / "already")
    monkeypatch.setattr(forge_code_projects, "is_thomas_owned", lambda _path: True)

    assert forge_code_projects.ensure_git_repo(project) is False


def test_a_folder_name_cannot_act_as_a_git_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git parses a leading "--" as an option, so passing a caller-supplied path
    as a positional argument lets the folder's NAME choose a flag. `--template`
    copies hooks out of the named directory, and those run on the next git
    command. Found by probing the bind route with adversarial paths."""
    hostile = tmp_path / "--template=evil"
    hostile.mkdir(parents=True)
    (hostile / "app.txt").write_text("content", encoding="utf-8")
    monkeypatch.setattr(forge_code_projects, "is_thomas_owned", lambda _path: True)

    assert forge_code_projects.ensure_git_repo(hostile) is True

    # The repository must exist INSIDE the oddly named folder, which only
    # happens when the path was the working directory rather than an argument.
    assert (hostile / ".git").is_dir()
    returncode, _stdout, _stderr = _run_git(hostile, ["rev-parse", "--verify", "HEAD"])
    assert returncode == 0
