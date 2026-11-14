"""Choosing no project must never mean "edit Thomas's own source".

That was the fallback, so a Code conversation arriving without a project --
including one whose JSON failed to parse and was treated as an empty body --
silently bound the product tree and returned 200. It is how a file of driving
tips ended up in the repository root.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.core.git_process import TIMED_OUT_RETURNCODE, GitResult
from thomas.forge.anvil import forge_code_projects
from thomas.server.routes.evolve_agent_routes import _new_task_project_root, _unspecified_project_root


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "--initial-branch=main"], capture_output=True, check=False)
    return path.resolve()


def test_a_deliberately_configured_repository_is_still_honoured(tmp_path: Path) -> None:
    """A root that is some other repo is a real choice, and callers rely on it."""
    root = _git_repo(tmp_path / "someproject")

    assert _unspecified_project_root(root) == root


def test_thomas_own_source_is_redirected_to_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _git_repo(tmp_path / "thomas_checkout")
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: root)
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(forge_code_projects, "default_scratch_project", lambda _r: scratch)

    assert _unspecified_project_root(root) == scratch


def test_a_root_that_cannot_be_bound_falls_back_rather_than_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In an installed copy the computed root is the package's parent, which is
    not a repository. Erroring there would leave someone unable to start."""
    not_a_repo = tmp_path / "site-packages"
    not_a_repo.mkdir()
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: tmp_path / "source")
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(forge_code_projects, "default_scratch_project", lambda _r: scratch)

    assert _unspecified_project_root(not_a_repo) == scratch


def test_a_non_checkout_install_uses_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed_root = tmp_path / "site-packages"
    installed_root.mkdir()
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: None)
    monkeypatch.setattr(forge_code_projects, "default_scratch_project", lambda _r: scratch)
    assert _unspecified_project_root(installed_root) == scratch


def test_new_task_does_not_fallback_when_catalog_inspection_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: tmp_path / "source")
    monkeypatch.setattr(
        forge_code_projects,
        "_git",
        lambda *_a, **_kw: GitResult(TIMED_OUT_RETURNCODE, "", "timed out", True, 0.1),
    )
    with pytest.raises(forge_code_projects.ForgeCodeInspectionUnavailable):
        _new_task_project_root(catalog, "make a game")


@pytest.mark.parametrize("selector", [_unspecified_project_root, _new_task_project_root])
def test_project_validation_inspection_failure_does_not_fall_back(
    selector, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _git_repo(tmp_path / "selected")
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: tmp_path / "other-source")

    def unavailable(*_args, **_kwargs) -> Path:
        raise forge_code_projects.ForgeCodeInspectionUnavailable("project_root could not be inspected")

    monkeypatch.setattr(forge_code_projects, "validate_project_root", unavailable)
    with pytest.raises(forge_code_projects.ForgeCodeInspectionUnavailable, match="could not be inspected"):
        if selector is _new_task_project_root:
            selector(root, "build a page")
        else:
            selector(root)


def test_new_task_creation_inspection_failure_does_not_use_shared_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _git_repo(tmp_path / "selected")
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: root)

    def unavailable(_task: str) -> Path:
        raise forge_code_projects.ForgeCodeInspectionUnavailable("project could not be inspected")

    monkeypatch.setattr(forge_code_projects, "project_for_new_task", unavailable)
    with pytest.raises(forge_code_projects.ForgeCodeInspectionUnavailable, match="could not be inspected"):
        _new_task_project_root(root, "build a page")


def test_an_unknown_source_root_does_not_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed source lookup must not select a plausible but unsafe root."""
    root = _git_repo(tmp_path / "elsewhere")

    def unavailable() -> Path:
        raise forge_code_projects.ForgeCodeProjectError("Thomas source root could not be inspected")

    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", unavailable)
    with pytest.raises(forge_code_projects.ForgeCodeProjectError, match="could not be inspected"):
        _unspecified_project_root(root)
