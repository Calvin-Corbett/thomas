"""The git tools hand git the path the scope validated, never the raw text, and never as pathspec magic or an option.

Git reads a leading ``:`` as pathspec magic (``:(top)``, ``:/``, ``:(glob)``) and a ref that starts with ``-`` as an
option. The magic gap existed before the files slot; the checks here close it for every call the tool makes.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from thomas.tools import git as git_tools
from thomas.tools.git import GitBlameTool, GitCommitTool, GitDiffTool, GitLogTool


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def world(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    (root / "sub").mkdir(parents=True)
    (root / "f.txt").write_text("x\n", encoding="utf-8")
    (root / "sub" / "g.txt").write_text("g\n", encoding="utf-8")
    (tmp_path / "x").write_text("secret\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "first")
    return root


def _run(tool, args):
    return asyncio.run(tool.execute(args))


MAGIC = (":(top)../x", ":/", ":(glob)*.txt", ":!f.txt", ":(top)f.txt", ":")


def _tools(root: Path, value: str):
    return [
        (GitDiffTool(root), {"path": value}),
        (GitLogTool(root), {"path": value}),
        (GitBlameTool(root), {"file": value}),
        (GitCommitTool(root), {"message": "m", "files": [value]}),
    ]


@pytest.mark.parametrize("value", MAGIC)
def test_a_value_that_starts_with_a_colon_is_refused(world, value) -> None:
    for tool, args in _tools(world, value):
        result = _run(tool, args)
        assert not result.ok, (type(tool).__name__, value)
        assert "outside project root" in str(result.error), (type(tool).__name__, value)


def test_a_normal_path_still_works(world) -> None:
    (world / "f.txt").write_text("y\n", encoding="utf-8")
    assert "+y" in _run(GitDiffTool(world), {"path": "f.txt"}).data
    assert _run(GitLogTool(world), {"path": "sub/g.txt"}).ok
    assert _run(GitBlameTool(world), {"file": "sub/g.txt"}).ok


def test_glob_characters_are_literal(world) -> None:
    (world / "f.txt").write_text("y\n", encoding="utf-8")
    # With no literal flag "*.txt" would match f.txt and show its change.
    assert "+y" not in str(_run(GitDiffTool(world), {"path": "*.txt"}).data)


class _Runs:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    async def __call__(self, *argv, **kwargs):
        self.calls.append((argv, kwargs))

        class _Proc:
            returncode = 0

            async def communicate(self):
                return b"", b""

        return _Proc()


@pytest.fixture
def runs(monkeypatch) -> _Runs:
    stub = _Runs()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", stub)
    return stub


def test_every_git_call_is_literal(world, runs) -> None:
    for tool, args in (
        (git_tools.GitStatusTool(world), {}),
        (GitDiffTool(world), {"path": "f.txt"}),
        (GitLogTool(world), {"path": "f.txt"}),
        (GitBlameTool(world), {"file": "f.txt"}),
        (GitCommitTool(world), {"message": "m", "files": ["f.txt"]}),
    ):
        _run(tool, args)
    assert len(runs.calls) >= 6
    for argv, kwargs in runs.calls:
        assert "--literal-pathspecs" in argv or kwargs.get("env", {}).get("GIT_LITERAL_PATHSPECS") == "1", argv


def test_git_gets_the_canonical_path_not_the_raw_text(world, runs) -> None:
    raw = "sub/../sub/./g.txt"
    _run(GitDiffTool(world), {"path": raw})
    _run(GitLogTool(world), {"path": str(world / "sub" / "g.txt")})
    _run(GitBlameTool(world), {"file": raw})
    _run(GitCommitTool(world), {"message": "m", "files": [raw]})
    for argv, _ in runs.calls:
        if "commit" in argv:
            continue
        assert raw not in argv, argv
        assert str(world) not in " ".join(argv), argv
        assert "sub/g.txt" in argv, argv
        assert argv[argv.index("sub/g.txt") - 1] == "--", argv


def test_a_dash_named_file_is_a_path_not_an_option(world, runs) -> None:
    _run(GitBlameTool(world), {"file": "-x"})
    argv = runs.calls[0][0]
    assert argv[argv.index("-x") - 1] == "--"


@pytest.mark.parametrize("ref", ["--output=pwned.txt", "-p", "--ext-diff", "-"])
def test_a_ref_that_starts_with_a_dash_is_refused(world, ref) -> None:
    result = _run(GitDiffTool(world), {"ref": ref})
    assert not result.ok
    assert "ref" in str(result.error).lower()
    assert not (world / "pwned.txt").exists()


def test_a_real_ref_still_works(world) -> None:
    assert _run(GitDiffTool(world), {"ref": "HEAD"}).ok
