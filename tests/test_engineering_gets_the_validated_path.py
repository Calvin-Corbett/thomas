"""The programs the engineering tools start get the path the scope validated, after "--", never the raw text.

A raw "--config=x" or "-x" resolves inside the root, passes the check, and would then be read by the program as an
option; "sub/../../work/f.py" leaves the root and comes back, and the program should still get the canonical name.
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from thomas.tools import engineering as eng


class _Runs:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    async def __call__(self, *argv, **kwargs):
        self.calls.append((argv, kwargs))
        out = b"{}" if "bandit" in argv else b"[]"

        class _Proc:
            returncode = 0

            async def communicate(self):
                return out, b""

        return _Proc()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / "f.py").write_text("import os\n", encoding="utf-8")
    return work


@pytest.fixture
def runs(monkeypatch) -> _Runs:
    stub = _Runs()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", stub)
    for name in ("vulture", "bandit"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    return stub


def _tools(root: Path):
    return [eng.DeadCodeTool(root), eng.SecurityScanTool(root), eng.CodeFormatTool(root), eng.LintTool(root)]


@pytest.mark.parametrize("raw", ["--config=x", "-x", "--output-file=y"])
def test_an_option_shaped_name_reaches_the_program_as_a_path(root, runs, raw) -> None:
    canonical = str(root.resolve() / raw)
    for tool in _tools(root):
        runs.calls.clear()
        assert asyncio.run(tool.execute({"path": raw})).ok, tool.name
        argv = runs.calls[0][0]
        assert raw not in argv, (tool.name, argv)
        assert canonical in argv, (tool.name, argv)
        assert argv[argv.index(canonical) - 1] == "--", (tool.name, argv)


def test_a_path_that_leaves_and_returns_is_given_in_its_canonical_form(root, runs) -> None:
    raw = "sub/../../work/f.py"
    canonical = str(root.resolve() / "f.py")
    for tool in _tools(root):
        runs.calls.clear()
        assert asyncio.run(tool.execute({"path": raw})).ok, tool.name
        argv = runs.calls[0][0]
        assert raw not in argv, (tool.name, argv)
        assert canonical in argv, (tool.name, argv)


def test_the_git_analysis_program_gets_the_canonical_repo_path(root, runs, monkeypatch) -> None:
    class _Err(Exception):
        pass

    fake = types.ModuleType("git")
    fake.Repo = lambda path: object()
    fake.InvalidGitRepositoryError = fake.NoSuchPathError = _Err
    monkeypatch.setitem(sys.modules, "git", fake)
    raw = "sub/../../work"
    assert asyncio.run(eng.GitAnalysisTool(root).execute({"repo_path": raw})).ok
    argv = runs.calls[0][0]
    assert str(root.resolve()) in argv and raw not in argv
