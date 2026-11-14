"""The write ladder allows the folders it names, not folders that read the same in lowercase.

``authorize_write`` asks one question twice with opposite stakes. On the allow side a false yes opens a folder that was
never granted: ``str.lower()`` turns U+212A KELVIN SIGN into ``k``, NTFS keeps the two apart, so a separate folder
spelled with that sign passed for an allowed root and ``fs.write_file`` wrote into it. On the deny side a false yes only
refuses one odd name, and a false no opens a system folder, so that side keeps the wider reading on purpose.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from thomas.core import file_access
from thomas.core.file_access import FULL, PC, PROJECT, WORKSPACE, authorize_write
from thomas.tools.filesystem import WriteFileTool

KELVIN = "K"

LADDER = {
    "workspace": (WORKSPACE, "workspace_root"),
    "project": (PROJECT, "project_root"),
    "your PC": (PC, "home_dir"),
}
each_rung = pytest.mark.parametrize(("level", "granted_by"), LADDER.values(), ids=LADDER.keys())


@pytest.fixture(
    params=[pytest.param("work", id="the root's own name"), pytest.param("Desktop/proj", id="a folder above the root")]
)
def twins(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Path, Path]:
    """A folder, and a separate one whose path differs from it by a Kelvin sign for a k."""
    root = tmp_path / request.param
    twin = tmp_path / request.param.replace("k", KELVIN)
    root.mkdir(parents=True)
    twin.mkdir(parents=True)
    if os.path.samefile(root, twin):
        pytest.skip("This disk folds the Kelvin sign, so these are not two folders")
    return root, twin


def _roots(tmp_path: Path, granted_by: str, root: Path) -> dict[str, Path]:
    """Every root the ladder reads, with only ``granted_by`` pointing at ``root``, so nothing else can allow it."""
    roots = {name: tmp_path / "elsewhere" / name for name in ("workspace_root", "project_root", "home_dir")}
    return {**roots, granted_by: root}


@each_rung
def test_the_ladder_does_not_take_a_twin_for_the_folder_it_allows(level, granted_by, twins, tmp_path) -> None:
    root, twin = twins
    roots = _roots(tmp_path, granted_by, root)
    allowed, reason = authorize_write(level, twin / "leak.txt", **roots)
    assert allowed is False, reason
    assert "outside what file access" in reason
    assert authorize_write(level, root / "inside.txt", **roots) == (True, "")


@each_rung
def test_the_write_tool_does_not_write_into_a_twin(level, granted_by, twins, tmp_path) -> None:
    root, twin = twins
    roots = _roots(tmp_path, granted_by, root)
    sandbox = roots["workspace_root"]
    sandbox.mkdir(parents=True, exist_ok=True)
    tool = WriteFileTool(sandbox, file_access=level, project_root=roots["project_root"], home_dir=roots["home_dir"])

    refused = asyncio.run(tool.execute({"path": str(twin / "leak.txt"), "content": "written"}))
    assert refused.ok is False, refused.data
    assert not (twin / "leak.txt").exists()

    written = asyncio.run(tool.execute({"path": str(root / "inside.txt"), "content": "written"}))
    assert written.ok is True, written.error
    assert (root / "inside.txt").read_text(encoding="utf-8") == "written"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path rules")
def test_a_folder_named_in_another_case_is_still_the_folder_allowed(tmp_path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    target = Path(str(root / "inside.txt").upper())
    allowed, reason = authorize_write(WORKSPACE, target, workspace_root=root)
    assert allowed is True, reason


@pytest.mark.parametrize("check", [file_access._path_within, file_access._reads_as_within], ids=["allow", "deny"])
@pytest.mark.parametrize("failure", [ValueError, OSError], ids=["ValueError", "OSError"])
def test_a_path_that_cannot_be_resolved_is_within_nothing(check, failure, tmp_path) -> None:
    class Unresolvable:
        def resolve(self) -> Path:
            raise failure("cannot be resolved")

    assert check(Unresolvable(), tmp_path) is False


@pytest.mark.parametrize("level", [WORKSPACE, PROJECT, PC, FULL], ids=["workspace", "project", "your PC", "full"])
def test_a_twin_of_a_denied_folder_stays_denied(level, twins, tmp_path, monkeypatch) -> None:
    """Not the denied folder, and refused anyway: the deny list must never read fewer names than it did."""
    root, twin = twins
    monkeypatch.setattr(file_access, "_system_deny_roots", lambda: [root])
    roots = _roots(tmp_path, "workspace_root", twin)
    for target in (root / "x.txt", twin / "x.txt"):
        allowed, reason = authorize_write(level, target, **roots)
        assert allowed is False, target
        assert file_access._REFUSAL_SYSTEM_DIR_MARK in reason
