"""code.repo_index and the Codex patch converter resolve every path through the files slot, so none leaves the root."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from thomas.tools import diff_codex_format as codex
from thomas.tools import fs_scope
from thomas.tools.diff_transaction import PatchFormatError
from thomas.tools.repo_code_index import RepoIndexTool


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "work"
    sibling = tmp_path / "work2"
    outside = tmp_path / "outside"
    for folder in (root, sibling, outside):
        folder.mkdir()
        (folder / "mod.py").write_text("def thing():\n    return 1\n", encoding="utf-8")
    return {"root": root, "sibling": sibling, "outside": outside}


def _index(root: Path, path: str):
    return asyncio.run(RepoIndexTool(root).execute({"path": path}))


def _patch(rel: str) -> str:
    return f"*** Begin Patch\n*** Update File: {rel}\n@@\n def thing():\n-    return 1\n+    return 2\n*** End Patch\n"


def _junction(world) -> str:
    if os.name != "nt":
        pytest.skip("junctions exist only on Windows")
    junction = world["root"] / "junction"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(world["outside"])], capture_output=True, text=True, check=False
    )
    if made.returncode != 0 or not junction.exists():
        pytest.skip("could not create a junction")
    return "junction"


def _escapes(world) -> list[str]:
    return [
        "../outside/mod.py",
        "sub/../../outside/mod.py",
        "../work2/mod.py",
        str(world["sibling"] / "mod.py"),
        str(world["outside"] / "mod.py"),
    ]


def test_repo_index_still_reads_a_file_inside(world) -> None:
    result = _index(world["root"], "mod.py")
    assert result.ok, result.error
    assert result.data["definitions"][0]["name"] == "thing"


@pytest.mark.parametrize("which", range(5))
def test_repo_index_refuses_every_way_out(world, which) -> None:
    result = _index(world["root"], _escapes(world)[which])
    assert not result.ok
    assert "escapes" in result.error or "outside" in result.error


def test_repo_index_refuses_a_junction_out(world) -> None:
    result = _index(world["root"], _junction(world) + "/mod.py")
    assert not result.ok


def test_repo_index_refuses_a_symlink_out(world) -> None:
    try:
        (world["root"] / "link").symlink_to(world["outside"], target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this account cannot create a symlink: {exc}")
    assert not _index(world["root"], "link/mod.py").ok


def test_repo_index_goes_through_the_scope_at_call_time(world, monkeypatch) -> None:
    seen: list[str] = []
    real = fs_scope.Scope.resolve

    def spy(self, rel):
        seen.append(rel)
        return real(self, rel)

    monkeypatch.setattr(fs_scope.Scope, "resolve", spy)
    assert _index(world["root"], "mod.py").ok
    assert "mod.py" in seen


def test_repo_index_refuses_a_case_changed_sibling_not_a_case_changed_root(world) -> None:
    if os.name != "nt":
        pytest.skip("case-insensitive paths exist only on Windows")
    swapped = str(world["root"] / "mod.py").swapcase()
    assert _index(world["root"], swapped).ok
    assert not _index(world["root"], str(world["sibling"] / "mod.py").swapcase()).ok


def test_codex_patch_still_converts_a_file_inside(world) -> None:
    out = codex.codex_patch_to_unified(_patch("mod.py"), world["root"])
    assert "+    return 2" in out


@pytest.mark.parametrize("which", range(5))
def test_codex_patch_refuses_every_way_out(world, which) -> None:
    with pytest.raises(PatchFormatError, match="escapes"):
        codex.codex_patch_to_unified(_patch(_escapes(world)[which]), world["root"])


def test_codex_patch_refuses_a_junction_out(world) -> None:
    with pytest.raises(PatchFormatError, match="escapes"):
        codex.codex_patch_to_unified(_patch(_junction(world) + "/mod.py"), world["root"])


def test_codex_patch_creates_nothing_outside_for_an_add(world) -> None:
    text = "*** Begin Patch\n*** Add File: ../work2/new.txt\n+x\n*** End Patch\n"
    with pytest.raises(PatchFormatError, match="escapes"):
        codex.convert_codex_patch(text, world["root"], create_files=True)
    assert not (world["sibling"] / "new.txt").exists()
