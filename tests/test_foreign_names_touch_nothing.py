"""A name on another drive or host is refused from its text alone: no filesystem call is made on it.

On Windows, a UNC name joined onto the root replaces the root with the network path, so a ``stat`` or ``is_symlink`` on
it contacts that server and offers the account's credentials before any check says the path is outside.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from thomas.tools import diff_codex_format as codex
from thomas.tools.diff_transaction import PatchFormatError
from thomas.tools.repo_code_index import RepoIndexTool

pytestmark = pytest.mark.skipif(os.name != "nt", reason="drive letters and UNC names exist only on Windows")

BS = chr(92)
FOREIGN = (
    BS * 2 + "evilhost" + BS + "share" + BS + "mod.py",
    "//evilhost/share/mod.py",
    "Z:/elsewhere/mod.py",
    "Z:" + BS + "elsewhere" + BS + "mod.py",
)


def _is_foreign(arg: object) -> bool:
    try:
        text = os.fspath(arg).replace("/", BS)  # type: ignore[arg-type]
    except TypeError:
        return False
    return text.lower().startswith((BS * 2 + "evilhost", "z:" + BS, BS * 2 + "?" + BS))


@pytest.fixture
def no_touch(monkeypatch) -> list[str]:
    """Fail the moment any filesystem call is made on a foreign name."""
    seen: list[str] = []

    def guard(real):
        def wrapped(*args, **kwargs):
            for arg in args:
                if _is_foreign(arg) or (hasattr(arg, "parts") and _is_foreign(str(arg))):
                    seen.append(str(arg))
                    pytest.fail(f"touched the filesystem on {arg!s}")
            return real(*args, **kwargs)

        return wrapped

    for owner, name in (
        (os, "stat"),
        (os, "lstat"),
        (os.path, "islink"),
        (os.path, "exists"),
        (os.path, "isfile"),
        (os.path, "isdir"),
        (os.path, "realpath"),
    ):
        monkeypatch.setattr(owner, name, guard(getattr(owner, name)))
    real_symlink = Path.is_symlink

    def is_symlink(self):
        if _is_foreign(str(self)):
            seen.append(str(self))
            pytest.fail(f"is_symlink on {self}")
        return real_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    return seen


@pytest.fixture
def root(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / "mod.py").write_text("def thing():\n    return 1\n", encoding="utf-8")
    return work


@pytest.mark.parametrize("name", FOREIGN)
def test_repo_index_refuses_a_foreign_name_without_touching_it(root, no_touch, name) -> None:
    result = asyncio.run(RepoIndexTool(root).execute({"path": name}))
    assert not result.ok
    assert "escapes" in result.error
    assert no_touch == []


@pytest.mark.parametrize("name", FOREIGN)
def test_codex_patch_refuses_a_foreign_name_without_touching_it(root, no_touch, name) -> None:
    text = f"*** Begin Patch\n*** Update File: {name}\n@@\n-a\n+b\n*** End Patch\n"
    with pytest.raises(PatchFormatError, match="escapes"):
        codex.codex_patch_to_unified(text, root)
    assert no_touch == []


def test_repo_index_refuses_a_junction_in_the_middle_of_the_path(root, tmp_path, no_touch) -> None:
    import subprocess

    (root / "real").mkdir()
    (root / "real" / "deep.py").write_text("def deep(): return 1" + chr(10), encoding="utf-8")
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root / "mid"), str(root / "real")], capture_output=True, check=False
    )
    if made.returncode != 0:
        pytest.skip("no junction on this account")
    assert asyncio.run(RepoIndexTool(root).execute({"path": "real/deep.py"})).ok
    refused = asyncio.run(RepoIndexTool(root).execute({"path": "mid/deep.py"}))
    assert not refused.ok and "outside the indexed" in refused.error


def test_repo_index_refuses_dotdot_in_the_text_and_takes_an_absolute_path_inside(root, no_touch) -> None:
    assert not asyncio.run(RepoIndexTool(root).execute({"path": "sub/../mod.py"})).ok
    assert asyncio.run(RepoIndexTool(root).execute({"path": str(root / "mod.py")})).ok


def test_repo_index_still_reads_a_file_and_a_link_leaf_inside_is_refused(root, no_touch) -> None:
    assert asyncio.run(RepoIndexTool(root).execute({"path": "mod.py"})).ok
    try:
        (root / "ln.py").symlink_to(root / "mod.py")
    except (OSError, NotImplementedError):
        pytest.skip("no symlink privilege on this account")
    assert not asyncio.run(RepoIndexTool(root).execute({"path": "ln.py"})).ok


@pytest.mark.parametrize("name", FOREIGN)
def test_redesign_undo_refuses_a_foreign_name_without_touching_it(root, no_touch, name) -> None:
    from thomas.forge.anvil import forge_code_redesign_undo as undo

    if name.replace(BS, "/").startswith("/"):
        # The leading slashes are stripped before the join, so a network name becomes a folder under the root.
        assert undo._safe_path(root, name).is_relative_to(root.resolve())
    else:
        with pytest.raises((undo.RedesignUndoError, ValueError)):
            undo._safe_path(root, name)
    assert no_touch == []
