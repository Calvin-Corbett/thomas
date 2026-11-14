"""The git tools stay in their root: a path that leaves it is refused, an ordinary path still works."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from thomas.tools.git import GitBlameTool, GitCommitTool, GitDiffTool, GitLogTool


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "work"
    sibling = tmp_path / "work2"
    outside = tmp_path / "outside"
    for folder in (root, sibling, outside):
        folder.mkdir()
        (folder / "f.txt").write_text("x\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "first")
    return {"base": tmp_path, "root": root, "sibling": sibling, "outside": outside}


def _run(tool, args):
    return asyncio.run(tool.execute(args))


def _calls(world, rel):
    root = world["root"]
    return [
        (GitDiffTool(root), {"path": rel}),
        (GitLogTool(root), {"path": rel}),
        (GitBlameTool(root), {"file": rel}),
        (GitCommitTool(root), {"message": "m", "files": [rel]}),
    ]


def _assert_refused(world, rel) -> None:
    for tool, args in _calls(world, rel):
        result = _run(tool, args)
        assert not result.ok, (type(tool).__name__, rel)
        assert "outside project root" in str(result.error), (type(tool).__name__, rel)


def test_ordinary_paths_inside_still_work(world) -> None:
    root = world["root"]
    assert _run(GitDiffTool(root), {"path": "f.txt"}).ok
    assert _run(GitLogTool(root), {"path": "f.txt"}).ok
    blame = _run(GitBlameTool(root), {"file": "f.txt"})
    assert blame.ok and "x" in blame.data
    assert _run(GitBlameTool(root), {"file": str(root / "f.txt")}).ok
    (root / "g.txt").write_text("g\n", encoding="utf-8")
    assert _run(GitCommitTool(root), {"message": "second", "files": ["g.txt"]}).ok


def test_dotdot_sibling_and_absolute_escapes_are_refused(world) -> None:
    for rel in (
        "../outside/f.txt",
        "sub/../../outside",
        "..",
        "../work2/f.txt",
        str(world["sibling"] / "f.txt"),
        str(world["outside"] / "f.txt"),
    ):
        _assert_refused(world, rel)


def test_a_refused_commit_stages_nothing(world) -> None:
    root = world["root"]
    (root / "g.txt").write_text("g\n", encoding="utf-8")
    result = _run(GitCommitTool(root), {"message": "m", "files": ["g.txt", "../outside/f.txt"]})
    assert not result.ok
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    assert staged.strip() == ""


def test_a_symlink_out_is_refused(world) -> None:
    try:
        (world["root"] / "link").symlink_to(world["outside"], target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this account cannot create a symlink: {exc}")
    _assert_refused(world, "link/f.txt")


def test_a_junction_out_is_refused(world) -> None:
    if os.name != "nt":
        pytest.skip("junctions exist only on Windows")
    junction = world["root"] / "junction"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(world["outside"])], capture_output=True, text=True, check=False
    )
    if made.returncode != 0 or not junction.exists():
        pytest.skip("could not create a junction")
    _assert_refused(world, "junction/f.txt")


def test_case_changes_inside_pass_and_other_folders_do_not(world) -> None:
    if sys.platform != "win32":
        pytest.skip("case-insensitive paths are a Windows rule")
    root = world["root"]
    assert _run(GitDiffTool(root), {"path": str(root / "f.txt").swapcase()}).ok
    refused = _run(GitDiffTool(root), {"path": str(world["sibling"] / "f.txt").swapcase()})
    assert not refused.ok and "outside project root" in str(refused.error)


def test_another_drive_or_unc_name_is_refused(world) -> None:
    if sys.platform != "win32":
        pytest.skip("drives and UNC names are a Windows rule")
    for rel in ("Z:\\nowhere\\f.txt", "\\\\server\\share\\f.txt"):
        _assert_refused(world, rel)


def test_the_scope_is_looked_up_per_call(world, monkeypatch) -> None:
    from thomas.tools import fs_scope

    seen: list[Path] = []

    class Spy:
        def scope(self, root):
            seen.append(Path(root))
            return fs_scope.Scope(root)

    monkeypatch.setattr(fs_scope, "scopes", lambda: Spy())
    assert _run(GitLogTool(world["root"]), {"path": "f.txt"}).ok
    assert seen
