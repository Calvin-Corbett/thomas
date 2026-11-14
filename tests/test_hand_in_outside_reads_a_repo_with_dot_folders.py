"""The hand-in command reads a repo that has folders like .github at its top, as Thomas itself does.

Proves scripts.crew.hand_in_outside and scripts.crew.hand_in_outside_checks. Ruff is given a copy of the repo's top-level
folders to tell first-party imports from the rest, and a folder named .github, .claude or .thomas can never be an import.
The check that keeps a name from leaving the lint folder refused any name starting with .git, so the command refused to
hand in anything from this repo (2026-11-03, the first real use). Every folder below is under tmp_path.
"""

from __future__ import annotations

import pytest
from scripts.crew import hand_in_outside as cli
from scripts.crew import hand_in_outside_build as build
from scripts.crew import hand_in_outside_checks as checks
from scripts.crew.hand_in_outside_build import Refusal

from tests.hand_in_outside_support import Repos, commit, git, make_repos, write


@pytest.fixture
def repos(tmp_path):
    return make_repos(tmp_path / "repos")


def _dot_folder_tip(repos: Repos) -> str:
    git(repos.clone, "checkout", "-q", "-b", "dots", repos.base)
    write(repos.clone, ".github/workflows/ci.yml", "name: ci\n")
    write(repos.clone, ".claude/notes.md", "notes\n")
    write(repos.clone, "pkg/tool.py", "VALUE = 3\n")
    return commit(repos.clone, "a repo with dot folders at its top")


def test_a_repo_with_dot_folders_at_its_top_is_handed_in_after_a_dry_run(repos, tmp_path, capsys):
    tip = _dot_folder_tip(repos)
    argv = ["--clone", str(repos.clone), "--base", repos.base, "--tip", tip, "--checkout", str(repos.checkout)]
    assert cli.main([*argv, "--inbox", str(tmp_path / "cage" / "inbox")], lint=checks.ruff_findings) == 0
    out = capsys.readouterr().out
    assert "will not write into the lint folder" not in out, out
    assert not (tmp_path / "cage" / "inbox").exists()  # a dry run writes nothing


def test_ruff_runs_on_a_repo_with_dot_folders_and_reports_what_the_change_adds(repos):
    tip = _dot_folder_tip(repos)
    git(repos.clone, "checkout", "-q", "-b", "dirty", tip)
    write(repos.clone, "pkg/tool.py", "import os\nVALUE = 3\n")
    dirty = commit(repos.clone, "an unused import")
    change = build.read_change(repos.clone, repos.base, dirty)
    ran, why, added = checks.ruff_findings(change)
    assert ran is True, why
    assert any("F401" in line or "os" in line for line in added), added


@pytest.mark.parametrize("odd", ["..", ".", "a\\b", "c:d", ".git\\x"])
def test_an_odd_top_level_name_is_still_refused_not_skipped(repos, monkeypatch, odd):
    change = build.read_change(repos.clone, repos.base, repos.plain)
    real = checks.git

    def listing(clone, *args, **kw):
        return f"pkg\0{odd}\0".encode() if args[0] == "ls-tree" else real(clone, *args, **kw)

    monkeypatch.setattr(checks, "git", listing)
    with pytest.raises(Refusal):
        checks.ruff_findings(change)
