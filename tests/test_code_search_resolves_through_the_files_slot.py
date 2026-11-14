"""The code.* tools ask the files slot whether a path is inside their root.

At 14c69b95 the five checks in ``code_search.py`` already compared folders (``path_is_inside``), so the shared-prefix
sibling was refused there; tests/test_code_tools_stay_inside_their_root.py holds that line. What was missing was the
slot: the tools decided on their own. These tests patch the slot at call time and see every site follow it, then run
the escapes and an ordinary path through the real scope.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thomas.tools import fs_scope
from thomas.tools.code_search import (
    CodeSearchTool,
    FindDefinitionTool,
    FindReferencesTool,
    ProjectStructureTool,
    _inside_root,
)


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    root, sibling = tmp_path / "work", tmp_path / "work2"
    for folder in (root, sibling):
        folder.mkdir()
        (folder / "m.py").write_text("def marker():\n    return 1\n", encoding="utf-8")
    return {"root": root, "sibling": sibling}


def _tools(root: Path) -> list[tuple[object, dict]]:
    search = CodeSearchTool(root)
    search._has_rg = False
    refs = FindReferencesTool(root)
    refs._has_rg = False
    return [
        (search, {"pattern": "marker"}),
        (FindDefinitionTool(root), {"symbol": "marker"}),
        (refs, {"symbol": "marker"}),
        (ProjectStructureTool(root), {}),
    ]


class _Refusing:
    """A files slot that lets nothing through, to show each site asks it."""

    asked: list[str]

    def __init__(self) -> None:
        self.asked = []

    def scope(self, root, /):
        asked = self.asked

        class _Scope:
            def __init__(self) -> None:
                self.root = Path(root)

            def resolve(self, rel: str) -> Path:
                asked.append(rel)
                raise ValueError("slot says no")

            def read_refusal(self, rel: str) -> str | None:
                return "BLOCKED: slot says no"

        return _Scope()


def test_every_site_asks_the_slot_at_call_time(world, monkeypatch) -> None:
    tools = _tools(world["root"])
    slot = _Refusing()
    monkeypatch.setattr(fs_scope, "scopes", lambda: slot)
    for tool, args in tools:
        result = asyncio.run(tool.execute({**args, "path": "."}))
        assert not result.ok, tool.name
    assert len(slot.asked) >= len(tools)


@pytest.mark.parametrize("rel", ["..", "../work2", "../work2/m.py", "sub/../../work2"])
def test_an_escape_is_refused(world, rel) -> None:
    with pytest.raises(ValueError, match="escapes sandbox"):
        _inside_root(world["root"].resolve(), rel)
    for tool, args in _tools(world["root"]):
        result = asyncio.run(tool.execute({**args, "path": rel}))
        assert not result.ok, tool.name
        assert "escapes sandbox" in (result.error or ""), tool.name


def test_the_sibling_by_absolute_path_is_refused(world) -> None:
    with pytest.raises(ValueError, match="escapes sandbox"):
        _inside_root(world["root"].resolve(), str(world["sibling"] / "m.py"))


def test_a_case_change_of_the_root_still_works_but_the_sibling_does_not(world) -> None:
    root = world["root"].resolve()
    assert _inside_root(root, str(root / "m.py")) == root / "m.py"
    with pytest.raises(ValueError):
        _inside_root(root, str(world["sibling"]).swapcase())


def test_the_signing_key_is_closed_to_the_tools(world) -> None:
    key = world["root"] / "runtime" / ".runtime_protection_key"
    key.parent.mkdir()
    key.write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="signing key"):
        _inside_root(world["root"].resolve(), "runtime/.runtime_protection_key")


def test_an_ordinary_path_inside_still_works(world) -> None:
    root = world["root"].resolve()
    assert _inside_root(root, "m.py") == root / "m.py"
    assert _inside_root(root, "new/dir") == root / "new" / "dir"
    for tool, args in _tools(world["root"]):
        result = asyncio.run(tool.execute({**args, "path": "."}))
        assert result.ok, (tool.name, result.error)
