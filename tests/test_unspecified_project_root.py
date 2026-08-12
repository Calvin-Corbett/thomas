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

from thomas.forge.anvil import forge_code_projects
from thomas.server.routes.evolve_agent_routes import _unspecified_project_root


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
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: None)
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(forge_code_projects, "default_scratch_project", lambda _r: scratch)

    assert _unspecified_project_root(not_a_repo) == scratch


def test_an_unknown_source_root_does_not_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """thomas_source_repo_root() returning None must not turn the guard off for
    a root that happens to be a valid repository -- it is only allowed through
    because it is bindable, not because the check was skipped."""
    root = _git_repo(tmp_path / "elsewhere")
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: None)

    assert _unspecified_project_root(root) == root
