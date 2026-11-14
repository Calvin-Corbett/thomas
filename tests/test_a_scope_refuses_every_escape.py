"""A path scope refuses every way out of its root.

The files slot (thomas/tools/fs_scope.py) is the one place that decides whether a path is inside a root. Each case
below is a way a path has got out, or could. The scope is used by nothing but these tests until the sites move onto it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from thomas.tools.fs_scope import Scope, scopes


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "work"
    sibling = tmp_path / "work2"
    outside = tmp_path / "outside"
    for folder in (root, sibling, outside):
        folder.mkdir()
        (folder / "f.txt").write_text("x", encoding="utf-8")
    return {"base": tmp_path, "root": root, "sibling": sibling, "outside": outside}


def test_a_path_inside_resolves(world) -> None:
    scope = scopes().scope(world["root"])
    assert isinstance(scope, Scope)
    assert scope.resolve("f.txt") == (world["root"] / "f.txt").resolve()
    assert scope.contains("new/dir/file.txt")


def test_dotdot_is_refused(world) -> None:
    scope = Scope(world["root"])
    assert not scope.contains("../outside/f.txt")
    assert not scope.contains("sub/../../outside")
    with pytest.raises(ValueError):
        scope.resolve("..")


def test_a_shared_prefix_sibling_is_refused(world) -> None:
    scope = Scope(world["root"])
    assert not scope.contains("../work2/f.txt")
    assert not scope.contains(str(world["sibling"] / "f.txt"))
    assert not scope.contains(str(world["sibling"]))


def test_an_absolute_path_elsewhere_is_refused(world) -> None:
    assert not Scope(world["root"]).contains(str(world["outside"] / "f.txt"))


def test_a_symlink_out_of_the_root_is_refused(world) -> None:
    link = world["root"] / "link"
    try:
        link.symlink_to(world["outside"], target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this account cannot create a symlink: {exc}")
    scope = Scope(world["root"])
    assert not scope.contains("link/f.txt")
    assert not scope.contains("link")


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
        pytest.skip(f"could not create a junction: {made.stdout.strip()} {made.stderr.strip()}")
    scope = Scope(world["root"])
    assert not scope.contains("junction/f.txt")
    assert not scope.contains("junction")


def test_case_differences_stay_inside_on_windows(world) -> None:
    if sys.platform != "win32":
        pytest.skip("case-insensitive paths are a Windows rule")
    root = world["root"]
    swapped = Scope(Path(str(root).swapcase()))
    assert swapped.contains("f.txt")
    assert Scope(root).contains(str(Path(str(root / "f.txt").swapcase())))
    # a different folder is still refused whatever its case
    assert not Scope(root).contains(str(world["sibling"]).swapcase())


def test_the_signing_key_is_not_readable_but_other_files_are(world) -> None:
    key = world["root"] / "runtime" / ".runtime_protection_key"
    key.parent.mkdir()
    key.write_text("secret", encoding="utf-8")
    scope = Scope(world["root"])
    assert "signing key" in (scope.read_refusal("runtime/.runtime_protection_key") or "")
    assert scope.read_refusal("f.txt") is None
    assert (scope.read_refusal("../outside/f.txt") or "").startswith("BLOCKED")


def test_filesystem_still_exports_the_moved_names() -> None:
    from thomas.tools import filesystem, fs_scope

    assert filesystem._safe_path is fs_scope._safe_path
    assert filesystem._is_read_protected_path is fs_scope._is_read_protected_path
