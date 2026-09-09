"""Shipped CLI commands must not require the development-only `scripts/` tree.

`pyproject.toml` ships only `thomas*` and `evolve_supervisor*`. `scripts/` --
the 59 enforcement gates, the commit tooling, the release helpers -- stays in the
repository and is absent from any installed copy. A shipped command that imports
from it at function scope therefore works perfectly for anyone who cloned the
repo and dies with `ModuleNotFoundError: No module named 'scripts'` for everyone
who ran `pip install`. That is invisible to a test suite run inside the repo,
which is why these tests simulate the installed shape explicitly.
"""

from __future__ import annotations

import importlib.abc
import json
import sys

import pytest
from click.testing import CliRunner


class _ScriptsAbsent(importlib.abc.MetaPathFinder):
    """Make `import scripts...` fail the way an installed copy would."""

    def find_spec(self, fullname, path=None, target=None):  # noqa: D102
        if fullname == "scripts" or fullname.startswith("scripts."):
            raise ModuleNotFoundError(f"No module named {fullname!r}")
        return None


@pytest.fixture()
def scripts_absent(monkeypatch):
    for name in [m for m in list(sys.modules) if m == "scripts" or m.startswith("scripts.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    finder = _ScriptsAbsent()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    return finder


def _run(args: list[str]):
    from thomas.cli.main import cli

    return CliRunner().invoke(cli, args)


def test_status_does_not_crash_without_the_scripts_tree(scripts_absent) -> None:
    result = _run(["status", "--json"])

    assert result.exit_code == 0, result.output
    assert not isinstance(result.exception, ModuleNotFoundError), result.exception


def test_status_reports_that_it_could_not_check_rather_than_claiming_clean(scripts_absent) -> None:
    """The degraded path must not look like a passing check.

    `ok: True` here would mean "worktree is clean" on the strength of a check
    that never ran. It must stay unknown and say why.
    """
    result = _run(["status", "--json"])
    payload = json.loads(result.output)
    worktree = payload.get("worktree") or {}

    assert worktree.get("ok") is not True, worktree
    blame = str(payload.get("worktree_error") or worktree.get("error") or "")
    assert "scripts" in blame, blame


def test_repo_clean_reports_the_import_failure_instead_of_raising(scripts_absent) -> None:
    result = _run(["repo-clean", "--json"])

    assert not isinstance(result.exception, ModuleNotFoundError), result.exception
