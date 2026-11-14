"""The engineering tools reach only what their workspace root holds.

Each tool that takes a path resolves it through the files slot (thomas/tools/fs_scope.py). Every way out is refused
with the tool's own error shape, before any program starts; an ordinary path inside still works, and the programs
the tools start run in the workspace.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from thomas.tools import engineering as eng
from thomas.tools.registry import ToolRegistry


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "work"
    sibling = tmp_path / "work2"
    outside = tmp_path / "outside"
    for folder in (root, sibling, outside):
        folder.mkdir()
        (folder / "f.py").write_text("import os\n", encoding="utf-8")
        (folder / "f.txt").write_text("hello", encoding="utf-8")
    return {"root": root, "sibling": sibling, "outside": outside}


class _Runs:
    """Stands in for asyncio.create_subprocess_exec and records how it was called."""

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
def runs(monkeypatch) -> _Runs:
    stub = _Runs()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", stub)
    for name in ("vulture", "bandit"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    class _Err(Exception):
        pass

    git = types.ModuleType("git")
    git.Repo = lambda path: object()
    git.InvalidGitRepositoryError = git.NoSuchPathError = _Err
    monkeypatch.setitem(sys.modules, "git", git)
    return stub


def _run(tool, path: str):
    return asyncio.run(tool.execute({"path": path, "repo_path": path}))


def _every_tool(root: Path):
    return [
        eng.DeadCodeTool(root),
        eng.SecurityScanTool(root),
        eng.CodeFormatTool(root),
        eng.LintTool(root),
        eng.ParseDocumentTool(root),
        eng.FileTypeTool(root),
        eng.DependencyTreeTool(root),
        eng.DetectEncodingTool(root),
        eng.GitAnalysisTool(root),
        eng.ProjectStatsTool(root),
    ]


def _ways_out(world: dict[str, Path]) -> dict[str, str]:
    ways = {
        "dotdot": "../outside/f.py",
        "deep dotdot": "sub/../../outside/f.py",
        "dotdot alone": "..",
        "sibling sharing a prefix": "../work2/f.py",
        "sibling by absolute name": str(world["sibling"] / "f.py"),
        "absolute elsewhere": str(world["outside"] / "f.py"),
        "sibling in other case": str(world["sibling"] / "f.py").swapcase(),
    }
    if os.name == "nt":
        ways["other drive"] = "Z:/elsewhere/f.py"
        ways["UNC name"] = os.sep * 2 + os.sep.join(["host", "share", "f.py"])
    return ways


def test_every_way_out_is_refused_before_a_program_starts(world, runs) -> None:
    for tool in _every_tool(world["root"]):
        for way, rel in _ways_out(world).items():
            result = _run(tool, rel)
            assert not result.ok, f"{tool.name} let '{way}' through"
            assert "escapes sandbox" in (result.error or ""), f"{tool.name} / {way}: {result.error}"
    assert runs.calls == []


def test_code_complexity_refuses_every_way_out(world) -> None:
    pytest.importorskip("radon")
    tool = eng.CodeComplexityTool(world["root"])
    for way, rel in _ways_out(world).items():
        result = _run(tool, rel)
        assert not result.ok and "escapes sandbox" in (result.error or ""), way


def test_a_junction_out_of_the_root_is_refused(world, runs) -> None:
    link = world["root"] / "out"
    if os.name == "nt":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(world["outside"])], capture_output=True)
        if made.returncode != 0:
            pytest.skip("no junction on this account")
    else:
        link.symlink_to(world["outside"], target_is_directory=True)
    for tool in _every_tool(world["root"]):
        result = _run(tool, "out/f.py")
        assert not result.ok and "escapes sandbox" in (result.error or ""), tool.name
    assert runs.calls == []


def test_a_symlink_out_of_the_root_is_refused(world, runs) -> None:
    link = world["root"] / "ln.py"
    try:
        link.symlink_to(world["outside"] / "f.py")
    except (OSError, NotImplementedError):
        pytest.skip("no symlink privilege on this account")
    for tool in _every_tool(world["root"]):
        result = _run(tool, "ln.py")
        assert not result.ok and "escapes sandbox" in (result.error or ""), tool.name


def test_in_process_tools_work_on_a_path_inside(world) -> None:
    root = world["root"]
    assert _run(eng.ParseDocumentTool(root), "f.txt").ok
    assert _run(eng.FileTypeTool(root), "f.py").ok
    assert _run(eng.DependencyTreeTool(root), "f.py").ok
    stats = _run(eng.ProjectStatsTool(root), ".")
    assert stats.ok and '"total_files": 2' in stats.data
    assert _run(eng.ProjectStatsTool(root), str(root)).ok
    assert not _run(eng.FileTypeTool(root), "missing.py").ok


def test_the_encoding_tool_reads_a_file_inside(world) -> None:
    pytest.importorskip("chardet")
    assert _run(eng.DetectEncodingTool(world["root"]), "f.txt").ok


def test_programs_run_in_the_workspace_on_a_path_inside(world, runs) -> None:
    root = world["root"].resolve()
    for tool in (eng.CodeFormatTool(root), eng.LintTool(root), eng.DeadCodeTool(root), eng.SecurityScanTool(root)):
        assert _run(tool, "f.py").ok, tool.name
    assert _run(eng.GitAnalysisTool(root), ".").ok
    assert len(runs.calls) == 5
    for argv, kwargs in runs.calls:
        assert Path(kwargs["cwd"]) == root, argv


def test_a_format_run_does_not_start_in_the_servers_folder(world, runs, monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    _run(eng.CodeFormatTool(world["root"]), "f.py")
    assert Path(runs.calls[0][1]["cwd"]).resolve() == world["root"].resolve()


def test_a_relative_path_is_read_from_the_root_not_the_servers_folder(world, monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(world["outside"])
    result = _run(eng.ParseDocumentTool(world["root"]), "f.txt")
    assert result.ok and "hello" in str(result.data)


def test_registration_takes_the_workspace_from_the_file_tools(world) -> None:
    from thomas.tools.filesystem import register_filesystem_tools

    reg = ToolRegistry()
    register_filesystem_tools(reg, world["root"])
    eng.register_engineering_tools(reg)
    assert Path(reg.get("eng.format_code")._scope().root).resolve() == world["root"].resolve()
    assert not _run(reg.get("eng.file_type"), "../outside/f.py").ok


def test_registration_without_a_workspace_keeps_the_working_folder() -> None:
    reg = ToolRegistry()
    eng.register_engineering_tools(reg)
    assert Path(reg.get("eng.format_code")._scope().root).resolve() == Path.cwd().resolve()
