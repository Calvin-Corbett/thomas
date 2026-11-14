"""The diff tools resolve every path through the files slot, so none reaches outside its root.

create_diff, preview_diff and the patch planner (preview_patch / apply_patch, with rollback) each name a file from
model text. Each way out of the root is refused with the tool's own error style, and ordinary paths inside still work.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from thomas.tools import diff as diff_mod
from thomas.tools import diff_transaction as txn_mod
from thomas.tools.diff import ApplyPatchTool, CreateDiffTool, PreviewDiffTool
from thomas.tools.diff_transaction import apply_patch_transactional, preflight_patch
from thomas.tools.fs_scope import Scope, Scopes


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "work"
    sibling = tmp_path / "work2"
    outside = tmp_path / "outside"
    for folder in (root, sibling, outside):
        folder.mkdir()
        (folder / "f.txt").write_text("old\n", encoding="utf-8")
    return {"base": tmp_path, "root": root, "sibling": sibling, "outside": outside}


def _run(coro):
    return asyncio.run(coro)


def _edit(tool_cls, root: Path, rel: str):
    tool = tool_cls(root) if tool_cls is PreviewDiffTool else tool_cls(root, root)
    return _run(tool.execute({"file": rel, "old_str": "old", "new_str": "new"}))


def _patch(rel: str) -> str:
    return f"--- a/{rel}\n+++ b/{rel}\n@@ -1 +1 @@\n-old\n+new\n"


def _apply(patch: str, world):
    return apply_patch_transactional(patch, world["root"], project_root=world["root"])


def _untouched(world) -> bool:
    return all((world[k] / "f.txt").read_text(encoding="utf-8") == "old\n" for k in ("outside", "sibling"))


def _escapes(world) -> dict[str, str]:
    cases = {
        "dotdot": "../outside/f.txt",
        "sibling_relative": "../work2/f.txt",
        "sibling_absolute": str(world["sibling"] / "f.txt"),
        "outside_absolute": str(world["outside"] / "f.txt"),
    }
    if sys.platform == "win32":
        cases["unc"] = r"\\someserver\share\f.txt"
        drive = "Y:" if str(world["root"]).upper().startswith("Z:") else "Z:"
        cases["other_drive"] = drive + "\\elsewhere\\f.txt"
    return cases


@pytest.mark.parametrize("tool_cls", [CreateDiffTool, PreviewDiffTool])
def test_a_single_file_edit_refuses_every_escape(world, tool_cls) -> None:
    for name, rel in _escapes(world).items():
        result = _edit(tool_cls, world["root"], rel)
        assert not result.ok, name
        assert "escapes sandbox" in (result.error or ""), name
    assert _untouched(world)


@pytest.mark.parametrize("tool_cls", [CreateDiffTool, PreviewDiffTool])
def test_a_single_file_edit_inside_the_root_still_works(world, tool_cls) -> None:
    sub = world["root"] / "sub"
    sub.mkdir()
    (sub / "g.txt").write_text("old\n", encoding="utf-8")
    assert _edit(tool_cls, world["root"], "f.txt").ok
    assert _edit(tool_cls, world["root"], "sub/g.txt").ok
    (world["root"] / "f.txt").write_text("old\n", encoding="utf-8")
    assert _edit(tool_cls, world["root"], "sub/../f.txt").ok


def test_the_patch_planner_refuses_every_escape_and_writes_nothing(world) -> None:
    for name, rel in _escapes(world).items():
        report = _apply(_patch(rel), world)
        assert not report.ok, name
        assert report.conflicts, name
        assert "escapes sandbox" in report.conflicts[0].reason, name
        assert not preflight_patch(_patch(rel), world["root"], project_root=world["root"]).ok, name
    assert _untouched(world)


def test_one_escaping_file_blocks_the_whole_patch(world) -> None:
    report = _apply(_patch("f.txt") + _patch("../outside/f.txt"), world)
    assert not report.ok
    assert (world["root"] / "f.txt").read_text(encoding="utf-8") == "old\n"
    assert _untouched(world)


def test_the_apply_tool_refuses_an_escape(world) -> None:
    result = _run(ApplyPatchTool(world["root"], world["root"]).execute({"patch": _patch("../outside/f.txt")}))
    assert not result.ok
    assert _untouched(world)


def test_apply_inside_the_root_still_applies(world) -> None:
    (world["root"] / "h.txt").write_text("old\n", encoding="utf-8")
    report = _apply(_patch("f.txt") + _patch("h.txt"), world)
    assert report.ok
    assert (world["root"] / "f.txt").read_text(encoding="utf-8") == "new\n"
    assert (world["root"] / "h.txt").read_text(encoding="utf-8") == "new\n"


def test_rollback_inside_the_root_still_restores(world, monkeypatch) -> None:
    (world["root"] / "h.txt").write_text("old\n", encoding="utf-8")
    real = Path.write_text
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky)
    report = _apply(_patch("f.txt") + _patch("h.txt"), world)
    assert not report.ok
    assert (world["root"] / "f.txt").read_text(encoding="utf-8") == "old\n"
    assert (world["root"] / "h.txt").read_text(encoding="utf-8") == "old\n"


def test_a_symlink_out_of_the_root_is_refused(world) -> None:
    link = world["root"] / "link"
    try:
        link.symlink_to(world["outside"], target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this account cannot create a symlink: {exc}")
    assert not _edit(CreateDiffTool, world["root"], "link/f.txt").ok
    assert not _apply(_patch("link/f.txt"), world).ok
    assert _untouched(world)


def test_a_junction_out_of_the_root_is_refused(world) -> None:
    if os.name != "nt":
        pytest.skip("junctions exist only on Windows")
    junction = world["root"] / "junction"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(world["outside"])],
        capture_output=True,
        text=True,
        check=False,
    )
    if made.returncode != 0 or not junction.exists():
        pytest.skip("could not create a junction")
    assert not _edit(CreateDiffTool, world["root"], "junction/f.txt").ok
    assert not _apply(_patch("junction/f.txt"), world).ok
    assert _untouched(world)


def test_a_case_change_of_the_root_stays_inside_on_windows(world) -> None:
    if sys.platform != "win32":
        pytest.skip("case-insensitive paths are a Windows rule")
    swapped = Path(str(world["root"]).swapcase())
    assert _edit(CreateDiffTool, swapped, "f.txt").ok
    assert not _edit(CreateDiffTool, world["root"], str(world["sibling"]).swapcase() + "\\f.txt").ok


@pytest.mark.parametrize("module", [diff_mod, txn_mod])
def test_the_tools_ask_the_files_slot_at_call_time(world, monkeypatch, module) -> None:
    asked: list[Path] = []

    class Spy(Scopes):
        def scope(self, root, /):
            asked.append(Path(root))
            return Scope(root)

    monkeypatch.setattr(module, "scopes", lambda: Spy(), raising=False)
    if module is diff_mod:
        assert _edit(CreateDiffTool, world["root"], "f.txt").ok
    else:
        assert _apply(_patch("f.txt"), world).ok
    assert asked
