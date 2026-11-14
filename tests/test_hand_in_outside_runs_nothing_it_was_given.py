"""Handing in an outside agent's change runs nothing the outside agent or its clone could name.

Proves scripts.crew.hand_in_outside, scripts.crew.hand_in_outside_checks and thomas.server.precard.lint. The outside
files and the clone's config below write a sentinel file if Python runs them; the sentinel must stay absent. Every folder is under tmp_path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from scripts.crew import hand_in_outside as cli
from scripts.crew import hand_in_outside_build as build
from scripts.crew import hand_in_outside_checks as checks
from scripts.crew.hand_in_outside_build import Refusal

from tests.hand_in_outside_support import Repos, commit, git, make_repos, write
from thomas.server.precard import lint


@pytest.fixture
def repos(tmp_path):
    return make_repos(tmp_path / "repos")


def _trap(sentinel) -> str:
    return f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n"


def _hand_in(repos: Repos, tmp_path, tip: str) -> int:
    argv = ["--clone", str(repos.clone), "--base", repos.base, "--tip", tip, "--checkout", str(repos.checkout)]
    return cli.main([*argv, "--inbox", str(tmp_path / "cage" / "inbox")], lint=checks.ruff_findings)


@pytest.mark.parametrize("planted", ["sitecustomize.py", "usercustomize.py", "ruff.py", "ruff/__init__.py", "x.pth"])
def test_a_change_that_brings_a_file_python_runs_on_start_is_not_linted(repos, tmp_path, capsys, planted):
    sentinel = tmp_path / "sentinel.txt"
    git(repos.clone, "checkout", "-q", "-b", "trap", repos.base)
    write(repos.clone, planted, _trap(sentinel))
    write(repos.clone, "pkg/new.py", "import os\n")  # something ruff would object to, were it run
    tip = commit(repos.clone, "plant a file")
    assert _hand_in(repos, tmp_path, tip) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert not sentinel.exists()
    assert "linting was skipped" in out and planted in out


def test_ruff_started_for_a_change_cannot_import_what_the_change_wrote(repos, tmp_path):
    sentinel = tmp_path / "sentinel.txt"
    for side in ("base", "change"):
        write(tmp_path / "work" / side, "pyproject.toml", '[tool.ruff.lint]\nselect = ["F"]\n')
        write(tmp_path / "work" / side, "ruff.py", _trap(sentinel))
        write(tmp_path / "work" / side, "sitecustomize.py", _trap(sentinel))
        write(tmp_path / "work" / side, "a.py", "import os\n" if side == "change" else "")
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    result = lint.ruff_findings(
        lambda: tmp_path / "work" / "base", tmp_path / "work" / "change", ["a.py"],
        python=sys.executable, data_dir=tmp_path / "data", trusted_cwd=trusted,
    )  # fmt: skip
    assert result.ran, result.why
    assert not sentinel.exists()
    assert any("a.py" in line and "F401" in line for line in result.added), result.added


def _booby_trap_the_clone(repos: Repos, tmp_path) -> tuple[str, Path]:
    """A change, then every way the clone's own config and attributes can name a program for git to start."""
    git(repos.clone, "checkout", "-q", "-b", "gitattr", repos.base)
    write(repos.clone, ".gitattributes", "*.py diff=trap\n*.txt filter=trap diff=trap\n")
    write(repos.clone, "pkg/more.py", "VALUE = 3\n")
    write(repos.clone, "pkg/tool.py", "VALUE = 4\n")
    tip = commit(repos.clone, "a change in a clone that is set to start a program")
    sentinel = tmp_path / "git-sentinel.txt"
    trap = tmp_path / "trap.py"
    trap.write_text(f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n", encoding="utf-8")
    run = f'python "{trap.as_posix()}"'
    for key in ("diff.external", "core.fsmonitor", "core.pager", "diff.trap.textconv", "diff.trap.command"):
        git(repos.clone, "config", key, run)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for hook in ("fsmonitor-watchman", "post-index-change", "reference-transaction", "post-checkout"):
        (hooks / hook).write_bytes(f"#!/bin/sh\n{run}\n".encode())
    git(repos.clone, "config", "core.hooksPath", str(hooks))
    return tip, sentinel


def test_the_clones_own_config_and_attributes_start_no_program(repos, tmp_path, capsys):
    tip, sentinel = _booby_trap_the_clone(repos, tmp_path)
    inbox = tmp_path / "cage" / "inbox"
    argv = ["--clone", str(repos.clone), "--base", repos.base, "--tip", tip, "--checkout", str(repos.checkout)]
    assert cli.main([*argv, "--inbox", str(inbox), "--drop", "--accept-card-wording"], lint=checks.ruff_findings) == 0
    assert not sentinel.exists(), capsys.readouterr().out
    assert len(list(inbox.iterdir())) == 1


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("a\\b.py", "backslash"),
        ("C:/x.py", "colon"),
        ("pkg/../../x.py", "'..'"),
        ("../x.py", "'..'"),
        ("./x.py", "'.'"),
        (".git/hooks/x.py", ".git"),
        (".github/x.py", ".git"),
        ("/etc/x.py", "absolute"),
        ("pkg/x\0.py", "NUL"),
        ("pkg//x.py", "empty"),
    ],
)
def test_a_name_that_could_leave_the_lint_folder_is_refused_in_plain_words(tmp_path, name, why):
    with pytest.raises(Refusal, match="will not write") as seen:
        checks.lint_target(tmp_path, "change", name)
    assert why in str(seen.value) and "nothing was handed in" in str(seen.value)
    assert list(tmp_path.iterdir()) == []


def test_the_changed_file_and_package_names_are_judged_before_anything_is_written(repos):
    clone = repos.clone
    for name in ("..\\x.py", "pkg/../../x.py"):
        change = build.Change(clone, repos.base, repos.plain, b"p", [name], [("a", "s")], "m")
        with pytest.raises(Refusal, match="will not write"):
            checks.ruff_findings(change)


def test_a_top_level_folder_name_git_lists_is_judged_too(repos, monkeypatch):
    change = build.read_change(repos.clone, repos.base, repos.plain)
    real = checks.git

    def listing(clone, *args, **kw):
        return b"pkg\0..\0" if args[0] == "ls-tree" else real(clone, *args, **kw)

    monkeypatch.setattr(checks, "git", listing)
    with pytest.raises(Refusal, match="'..'"):
        checks.ruff_findings(change)


def test_a_name_that_stays_inside_is_given_a_place_under_the_side_folder(tmp_path):
    target = checks.lint_target(tmp_path, "base", "pkg/tool.py")
    assert target.resolve().is_relative_to((tmp_path / "base").resolve())


def test_a_file_named_like_an_option_is_never_handed_to_ruff_as_one(tmp_path, monkeypatch):
    seen: list[list[str]] = []

    def capture(command, *, cwd, env, timeout_s):
        seen.append(list(command))
        return 0, ""

    monkeypatch.setattr(lint, "run_quietly", capture)
    names = ["-bad.py", "--config=evil.py", "ok.py"]
    for name in names:
        write(tmp_path / "work", name, "X = 1\n")
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    lint.ruff_findings(
        lambda: tmp_path / "work", tmp_path / "work", names,
        python=sys.executable, data_dir=tmp_path / "data", trusted_cwd=trusted,
    )  # fmt: skip
    assert seen
    for command in seen:
        assert "--" in command, command
        options, files = command[: command.index("--")], command[command.index("--") + 1 :]
        assert not any(name in option for option in options for name in names), command
        assert len(files) == 3 and all(Path(item).is_absolute() for item in files), command


def test_a_change_with_a_path_part_starting_with_a_dash_is_refused_in_plain_words(repos):
    change = build.Change(repos.clone, repos.base, repos.plain, b"p", ["pkg/--config=evil.py"], [("a", "s")], "m")
    with pytest.raises(Refusal, match="will not write") as seen:
        checks.ruff_findings(change)
    assert "starting with a dash" in str(seen.value) and "nothing was handed in" in str(seen.value)
