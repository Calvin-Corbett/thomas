"""A ``code.*`` tool looks inside its root and nowhere else.

The five path checks in ``thomas/tools/code_search.py`` were ``str(path).startswith(str(root))``. That compares
characters, not folders: ``C:\\x\\work2`` starts with ``C:\\x\\work``, so the folder beside the root read as inside it,
and so did anything that resolved there. The agent loop refuses ``..`` and absolute paths before a tool runs, but a link
inside the root has neither, so this reached agent calls as well.

Every escape runs against every way into those checks, so one check left behind fails by name. The second half is the
other direction: tightening a boundary is only a fix if what was inside it still works.
"""

from __future__ import annotations

import asyncio
import ntpath
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from thomas.core.file_access import path_is_inside
from thomas.tools import code_search, code_search_scan
from thomas.tools.base import Tool, ToolResult
from thomas.tools.code_search import (
    CodeSearchTool,
    FindDefinitionTool,
    FindReferencesTool,
    ProjectStructureTool,
    _inside_root,
)
from thomas.tools.filesystem import _safe_path

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows path rules")

Built = tuple[Tool, dict[str, Any]]


def _search(root: Path, *, rg: bool) -> Built:
    tool = CodeSearchTool(root)
    tool._has_rg = rg
    return tool, {"pattern": "def marker"}


def _definition(root: Path, **extra: str) -> Built:
    return FindDefinitionTool(root), {"symbol": "marker", **extra}


def _references(root: Path, *, rg: bool) -> Built:
    tool = FindReferencesTool(root)
    tool._has_rg = rg
    return tool, {"symbol": "marker"}


def _structure(root: Path) -> Built:
    return ProjectStructureTool(root), {}


SITES: dict[str, Callable[[Path], Built]] = {
    "code.search with rg": partial(_search, rg=True),
    "code.search in Python": partial(_search, rg=False),
    "code.find_definition": _definition,
    "code.find_definition by the Python index": partial(_definition, language="python"),
    "code.find_references with rg": partial(_references, rg=True),
    "code.find_references in Python": partial(_references, rg=False),
    "code.project_structure": _structure,
}
each_site = pytest.mark.parametrize("site", SITES.values(), ids=SITES.keys())


def _call(built: Built, path: str) -> ToolResult:
    tool, args = built
    return asyncio.run(tool.execute({**args, "path": path}))


def _symlink(link: Path, target: Path) -> str:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Cannot make a symbolic link here: {exc}")
    return link.name


def _junction(link: Path, target: Path) -> str:
    import _winapi

    _winapi.CreateJunction(str(target), str(link))
    return link.name


def _plant(folder: Path) -> None:
    (folder / "leak.py").write_text("def marker():\n    return 'outside'\n", encoding="utf-8")


def _assert_refused(result: ToolResult) -> None:
    assert result.ok is False, result.data
    assert "escapes sandbox" in str(result.error)
    assert "leak.py" not in str(result.data)


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    """A root and the folder beside it, whose name starts with the root's."""
    root = tmp_path / "work"
    sibling = tmp_path / "work2"
    (root / "pkg").mkdir(parents=True)
    sibling.mkdir()
    (root / "pkg" / "inside.py").write_text("def marker():\n    return 'root'\n", encoding="utf-8")
    _plant(sibling)
    return root, sibling


@pytest.mark.parametrize(
    "escape",
    [
        pytest.param(lambda root, sibling: f"../{sibling.name}", id="relative"),
        pytest.param(lambda root, sibling: str(sibling), id="absolute"),
        pytest.param(lambda root, sibling: str(sibling / "leak.py"), id="one file"),
        pytest.param(lambda root, sibling: f"{root}_not_there_yet", id="beside and not there yet"),
        pytest.param(lambda root, sibling: "..", id="the parent"),
        pytest.param(lambda root, sibling: _symlink(root / "link", sibling), id="symbolic link"),
        pytest.param(lambda root, sibling: _junction(root / "link", sibling), id="junction", marks=windows_only),
        pytest.param(lambda root, sibling: f"../{sibling.name.upper()}", id="another case", marks=windows_only),
        pytest.param(lambda root, sibling: "Z:\\nothing", id="another drive", marks=windows_only),
    ],
)
@each_site
def test_a_path_outside_the_root_is_refused(site, escape, folders) -> None:
    root, sibling = folders
    _assert_refused(_call(site(root), escape(root, sibling)))


@pytest.mark.parametrize(
    "link",
    [pytest.param(_symlink, id="symbolic link"), pytest.param(_junction, id="junction", marks=windows_only)],
)
@each_site
def test_a_root_swapped_for_a_link_after_the_tool_was_built_is_refused(site, link, tmp_path: Path) -> None:
    """The root is the folder the tool was built with, not wherever that name points now."""
    root = tmp_path / "work"
    elsewhere = tmp_path / "elsewhere"
    root.mkdir()
    elsewhere.mkdir()
    _plant(elsewhere)
    built = site(root)
    root.rmdir()
    link(root, elsewhere)
    _assert_refused(_call(built, "."))


@pytest.mark.parametrize(
    "inside",
    [
        pytest.param(lambda root: ".", id="the root"),
        pytest.param(lambda root: "pkg", id="a folder"),
        pytest.param(lambda root: "pkg/../pkg", id="dots that stay inside"),
        pytest.param(lambda root: str(root / "pkg"), id="absolute"),
        pytest.param(lambda root: _symlink(root / "link", root / "pkg"), id="a symbolic link that stays inside"),
        pytest.param(
            lambda root: _junction(root / "link", root / "pkg"), id="a junction that stays inside", marks=windows_only
        ),
        pytest.param(lambda root: str(root / "pkg").upper(), id="another case", marks=windows_only),
        pytest.param(lambda root: str(root / "pkg").lower(), id="a lowercase drive letter", marks=windows_only),
    ],
)
@each_site
def test_a_path_inside_the_root_still_works(site, inside, folders) -> None:
    root, _sibling = folders
    result = _call(site(root), inside(root))
    assert result.ok is True, result.error
    assert "inside.py" in str(result.data)


@windows_only
def test_a_root_named_in_another_case_still_owns_its_folders(tmp_path: Path) -> None:
    """Characters differ, the folder does not. The string test refused this one the other way round."""
    built = _structure(tmp_path / "WORK")
    (tmp_path / "work" / "pkg").mkdir(parents=True)
    result = _call(built, "pkg")
    assert result.ok is True, result.error


# ---------------------------------------------------------------------------
# The disk decides which names are the same
# ---------------------------------------------------------------------------

# On Windows ``Path.is_relative_to``, ``Path ==`` and ``os.path.commonpath`` compare with ``str.lower()``, which turns
# U+212A KELVIN SIGN into ``k``. NTFS keeps the two apart, so they are two real folders that compare as one.
KELVIN = "\u212a"


def _code_tools_check(root: Path, path: str) -> None:
    _inside_root(root.resolve(), path)


def _fs_tools_check(root: Path, path: str) -> None:
    _safe_path(root, path)


# The agent loop's own check is held by tests/test_the_agent_loop_holds_the_same_line_as_the_tools.py.
CHECKS: dict[str, Callable[[Path, str], None]] = {
    "the code tools": _code_tools_check,
    "the fs tools": _fs_tools_check,
}
each_check = pytest.mark.parametrize("check", CHECKS.values(), ids=CHECKS.keys())


@pytest.fixture(
    params=[pytest.param("work", id="the root's own name"), pytest.param("Desktop/proj", id="a folder above the root")]
)
def twins(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Path, Path]:
    """A root, and a separate folder whose path differs from it by a Kelvin sign for a k."""
    root = tmp_path / request.param
    twin = tmp_path / request.param.replace("k", KELVIN)
    (root / "pkg").mkdir(parents=True)
    twin.mkdir(parents=True)
    (root / "pkg" / "inside.py").write_text("def marker():\n    return 'root'\n", encoding="utf-8")
    _plant(twin)
    if os.path.samefile(root, twin):
        pytest.skip("This disk folds the Kelvin sign, so these are not two folders")
    return root, twin


@pytest.mark.parametrize(
    "spell",
    [
        pytest.param(lambda root, twin: str(twin), id="absolute"),
        pytest.param(lambda root, twin: str(twin / "leak.py"), id="one file"),
        pytest.param(lambda root, twin: os.path.relpath(twin, root), id="relative"),
    ],
)
@each_site
def test_a_twin_of_the_root_is_refused(site, spell, twins) -> None:
    root, twin = twins
    _assert_refused(_call(site(root), spell(root, twin)))


@each_check
def test_no_check_takes_a_twin_for_the_root(check, twins) -> None:
    root, twin = twins
    with pytest.raises(ValueError, match="(?i)sandbox"):
        check(root, str(twin / "leak.py"))
    check(root, str(root / "pkg" / "inside.py"))


def test_inside_compares_folder_by_folder() -> None:
    assert path_is_inside(Path("/x/work/pkg"), Path("/x/work"))
    assert path_is_inside(Path("/x/work"), Path("/x/work"))
    assert not path_is_inside(Path("/x/work2"), Path("/x/work"))
    assert not path_is_inside(Path("/x"), Path("/x/work"))
    assert path_is_inside(Path("/x/work"), Path("/"))


# ---------------------------------------------------------------------------
# A walk stays on this side of every link
# ---------------------------------------------------------------------------

LINKS = [pytest.param(_symlink, id="symbolic link"), pytest.param(_junction, id="junction", marks=windows_only)]
each_link = pytest.mark.parametrize("link", LINKS)


def _call_with_no_path(built: Built, **extra: Any) -> ToolResult:
    tool, args = built
    return asyncio.run(tool.execute({**args, **extra}))


@pytest.mark.parametrize("where", ["door", "pkg/door"], ids=["at the top", "further down"])
@each_link
@each_site
def test_a_walk_does_not_leave_through_a_link(site, link, where, folders) -> None:
    root, sibling = folders
    link(root / where, sibling)
    result = _call_with_no_path(site(root))
    assert result.ok is True, result.error
    assert "inside.py" in str(result.data)
    assert "leak.py" not in str(result.data)


@each_site
def test_a_walk_does_not_read_through_a_link_to_a_file(site, folders) -> None:
    root, sibling = folders
    try:
        (root / "linked.py").symlink_to(sibling / "leak.py")
    except OSError as exc:
        pytest.skip(f"Cannot make a symbolic link here: {exc}")
    result = _call_with_no_path(site(root))
    assert result.ok is True, result.error
    assert "linked.py:" not in str(result.data)


@each_link
@each_site
def test_a_walk_finds_a_file_once_when_a_link_also_leads_to_it(site, link, folders) -> None:
    root, _sibling = folders
    link(root / "again", root / "pkg")
    result = _call_with_no_path(site(root))
    assert result.ok is True, result.error
    assert str(result.data).count("inside.py") == 1


def test_a_listing_calls_a_symbolic_link_a_link_on_a_machine_that_cannot_make_one(monkeypatch) -> None:
    """The symbolic link cases above skip wherever the account may not create links, and this branch must not."""

    class Entry:
        name = "door"

        def is_symlink(self) -> bool:
            return True

        def is_dir(self, *, follow_symlinks: bool = True) -> bool:
            return follow_symlinks

    @contextmanager
    def listing(_folder: object) -> Iterator[list[Entry]]:
        yield [Entry()]

    monkeypatch.setattr(code_search_scan.os, "scandir", listing)
    assert code_search_scan.list_folder("anywhere") == ([], [], ["door"])


@each_link
@pytest.mark.parametrize("show_files", [True, False], ids=["with files", "folders only"])
def test_the_tree_names_a_link_and_does_not_open_it(link, show_files, folders) -> None:
    root, sibling = folders
    link(root / "door", sibling)
    data = str(_call_with_no_path(_structure(root), show_files=show_files).data)
    assert "door (link, not followed)" in data
    assert "pkg/" in data
    assert "leak.py" not in data


# ---------------------------------------------------------------------------
# Caller text reaches rg only as a value
# ---------------------------------------------------------------------------

each_search = pytest.mark.parametrize("rg", [True, False], ids=["with rg", "in Python"])


@windows_only
@each_search
def test_a_pattern_that_looks_like_a_flag_does_not_follow_a_junction(rg, folders) -> None:
    root, sibling = folders
    _junction(root / "door", sibling)
    (root / "pkg" / "dash.py").write_text("x = '-Lemarker'\n", encoding="utf-8")
    tool, _ = _search(root, rg=rg)
    result = asyncio.run(tool.execute({"pattern": "-Lemarker"}))
    assert result.ok is True, result.error
    assert "dash.py" in str(result.data)
    assert "leak.py" not in str(result.data)


@each_search
def test_a_pattern_that_looks_like_a_flag_does_not_read_a_file_of_patterns(rg, folders) -> None:
    root, sibling = folders
    outside = sibling / "patterns.txt"
    outside.write_text("def marker\n", encoding="utf-8")
    tool, _ = _search(root, rg=rg)
    result = asyncio.run(tool.execute({"pattern": f"--file={outside.as_posix()}"}))
    assert result.ok is True, result.error
    assert "inside.py" not in str(result.data)


def test_a_pattern_that_looks_like_a_flag_does_not_run_a_program(folders, monkeypatch) -> None:
    """``--pre=`` takes the pattern's place, so rg reads the path as the pattern and searches its working folder.

    That needs a path that parses as a regex. ``C:\\work\\src`` and every POSIX path do; the path this suite runs under
    does not (``\\o`` is no escape), so ``pkg`` stands in for one here.
    """
    root, _sibling = folders
    (root / "pkg" / "ran.py").write_text(
        "from pathlib import Path\nPath(__file__).with_name('it_ran.txt').write_text('ran')\n", encoding="utf-8"
    )
    monkeypatch.setattr(code_search, "_inside_root", lambda _root, _rel: Path("pkg"))
    tool, _ = _search(root, rg=True)
    result = asyncio.run(tool.execute({"pattern": f"--pre={Path(sys.executable).as_posix()}"}))
    assert result.ok is True, result.error
    assert not (root / "pkg" / "it_ran.txt").exists()


@pytest.mark.parametrize(
    "make, args",
    [
        pytest.param(partial(_search, rg=True), {"pattern": "--hidden"}, id="code.search"),
        pytest.param(partial(_references, rg=True), {"symbol": "--hidden"}, id="code.find_references"),
    ],
)
def test_rg_is_told_where_the_flags_end(make, args, folders, monkeypatch) -> None:
    root, _sibling = folders
    commands: list[tuple[str, ...]] = []

    async def spy(*command: str, **_kwargs: Any) -> None:
        commands.append(command)
        raise FileNotFoundError("the test stops here, before rg starts")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    tool, _ = make(root)
    asyncio.run(tool.execute({**args, "max_results": 5}))
    command = commands[0]
    pattern_at = command.index("-e") + 1
    assert "hidden" in command[pattern_at], command
    assert "--hidden" not in command[:pattern_at], command
    assert command[pattern_at + 1 :] == ("--", str(root.resolve())), command
    assert "--max-count=5" in command, command


def test_a_glob_that_looks_like_a_flag_stays_a_glob(folders, monkeypatch) -> None:
    root, _sibling = folders
    commands: list[tuple[str, ...]] = []

    async def spy(*command: str, **_kwargs: Any) -> None:
        commands.append(command)
        raise FileNotFoundError("the test stops here, before rg starts")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    tool, args = _search(root, rg=True)
    asyncio.run(tool.execute({**args, "glob": "--hidden"}))
    assert "--glob=--hidden" in commands[0], commands[0]


# ---------------------------------------------------------------------------
# A network path is refused from its text
# ---------------------------------------------------------------------------

HOST = "thomas-spy.invalid"
NETWORK_PATHS = {
    "a share": rf"\\{HOST}\share\x",
    "forward slashes": f"//{HOST}/share/x",
    "mixed slashes": rf"/\{HOST}\share\x",
    "three slashes": rf"\\\{HOST}\share\x",
    "verbatim": rf"\\?\UNC\{HOST}\share\x",
    "device": rf"\\.\UNC\{HOST}\share\x",
    "native": rf"\??\UNC\{HOST}\share\x",
    "no share": rf"\\{HOST}",
}
each_network_path = pytest.mark.parametrize("path", NETWORK_PATHS.values(), ids=NETWORK_PATHS.keys())


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What tried to touch the fake host. The real call never runs, so nothing here can reach a network."""
    touched: list[str] = []

    def guard(owner: Any, name: str) -> None:
        real = getattr(owner, name)

        def spy(path: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(path, (str, os.PathLike)) and HOST in os.fspath(path):
                touched.append(f"{name}({os.fspath(path)})")
                raise FileNotFoundError(2, "stopped by the test", os.fspath(path))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(owner, name, spy)

    guard(ntpath, "_getfinalpathname")
    for name in ("stat", "lstat", "readlink", "scandir"):
        guard(os, name)
    return touched


@windows_only
@each_network_path
@each_site
def test_a_network_path_is_refused_before_anything_opens_it(site, path, folders, opened) -> None:
    root, _sibling = folders
    _assert_refused(_call(site(root), path))
    assert opened == []


@windows_only
@each_site
def test_another_drive_is_refused_before_anything_opens_it(site, folders, monkeypatch) -> None:
    root, _sibling = folders
    built = site(root)
    tried: list[str] = []
    real = ntpath._getfinalpathname

    def spy(path: str) -> str:
        if path.upper().startswith("Z:"):
            tried.append(path)
            raise FileNotFoundError(2, "stopped by the test", path)
        return real(path)

    monkeypatch.setattr(ntpath, "_getfinalpathname", spy)
    _assert_refused(_call(built, "Z:\\nothing"))
    assert tried == []


# ---------------------------------------------------------------------------
# The signing key is as closed to the code tools as it is to the fs tools
# ---------------------------------------------------------------------------

KEY = "runtime/.runtime_protection_key"
KEY_TEXT = "a-fake-key-made-for-this-test"


@pytest.fixture
def key_root(folders: tuple[Path, Path]) -> Path:
    root, _sibling = folders
    (root / "runtime").mkdir()
    (root / KEY).write_text(f"{KEY_TEXT}\n", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "spell",
    [
        pytest.param(lambda root: KEY, id="by name"),
        pytest.param(lambda root: str(root / KEY), id="absolute"),
        pytest.param(lambda root: KEY.upper(), id="another case", marks=windows_only),
        pytest.param(lambda root: f"{KEY}::$DATA", id="its data stream", marks=windows_only),
        pytest.param(lambda root: f"{KEY}.", id="a trailing dot", marks=windows_only),
        pytest.param(
            lambda root: f"{_junction(root / 'door', root / 'runtime')}/.runtime_protection_key",
            id="through a junction",
            marks=windows_only,
        ),
    ],
)
@each_site
def test_naming_the_key_is_refused(site, spell, key_root) -> None:
    result = _call(site(key_root), spell(key_root))
    assert result.ok is False, result.data
    assert "BLOCKED" in str(result.error)


@each_search
def test_the_key_named_outright_is_not_searched(rg, key_root) -> None:
    tool, _ = _search(key_root, rg=rg)
    result = asyncio.run(tool.execute({"pattern": KEY_TEXT, "path": KEY}))
    assert KEY_TEXT not in str(result.data)


@pytest.mark.parametrize(
    "args",
    [
        pytest.param({}, id="from the root"),
        pytest.param({"path": "runtime"}, id="from its folder"),
        pytest.param({"glob": ".runtime*"}, id="a glob that asks for it"),
        pytest.param({"glob": "*"}, id="a glob for everything"),
        pytest.param({"path": "runtime", "glob": ".runtime*"}, id="its folder and a glob"),
    ],
)
@each_search
def test_a_walk_does_not_read_the_key_on_its_way_past(rg, args, key_root) -> None:
    tool, _ = _search(key_root, rg=rg)
    result = asyncio.run(tool.execute({"pattern": KEY_TEXT, **args}))
    assert result.ok is True, result.error
    assert KEY_TEXT not in str(result.data)


# ---------------------------------------------------------------------------
# A root that is not there
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "site",
    [SITES["code.search with rg"], SITES["code.find_references with rg"]],
    ids=["code.search", "code.find_references"],
)
def test_a_root_that_does_not_exist_gets_an_answer(site, tmp_path: Path) -> None:
    result = _call_with_no_path(site(tmp_path / "gone"))
    assert result.ok is True, result.error
    assert "No " in str(result.data)
