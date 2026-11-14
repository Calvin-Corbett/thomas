"""What the six notification tools do inside their folder, and the names they refuse before they touch the disk.

``thomas.notifications.tools`` takes a database name from a model, so the name is resolved through the files slot
(``thomas.tools.fs_scope``) against one folder. A name on another drive or a network share is refused from its text,
before the scope, the disk or SQLite is reached. ``thomas.server.rows.notifications`` builds the scope for the real
tools, from the memory folder of the server.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from thomas.notifications import store as store_module
from thomas.notifications.tools import build_notifications_tools
from thomas.tools.fs_scope import Scope, scopes


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    inside = tmp_path / "notifications"
    inside.mkdir()
    return inside


@pytest.fixture
def tools(folder: Path) -> dict[str, Any]:
    return {tool.name: tool for tool in build_notifications_tools(scopes().scope(folder))}


def _call(tools: dict[str, Any], name: str, **args: Any) -> Any:
    return _run(tools[name].safe_execute(args))


def test_the_six_tools_are_built_and_keep_their_names(tools: dict[str, Any]) -> None:
    assert sorted(tools) == [
        "notifications_clear",
        "notifications_create",
        "notifications_get_store",
        "notifications_get_unread_count",
        "notifications_list",
        "notifications_mark_read",
    ]


def test_a_store_is_made_inside_the_folder_and_the_tools_that_work_answer(tools: dict[str, Any], folder: Path) -> None:
    made = _call(tools, "notifications_get_store", store_path="mine.sqlite")
    assert made.ok, made.error
    assert Path(made.data["store_path"]) == (folder / "mine.sqlite").resolve()
    assert _call(tools, "notifications_get_unread_count", store_path="mine.sqlite").data == {"unread_count": 0}
    assert _call(tools, "notifications_list", store_path="mine.sqlite").data == {"total": 0, "notifications": []}
    assert _call(tools, "notifications_mark_read", store_path="mine.sqlite", notification_id="n1").ok


# The tools were written against methods the store does not have: it has ``add`` and not ``create``, its ``clear`` takes
# a mode and not a severity, it has no ``mark_all_read``, and a notification has ``timestamp`` and not ``created_at``.
# So no tool can put a notification into a store, and the row's words say so. Each of these turns into a failure when one
# is mended, which is the reminder to change the words.
BROKEN = pytest.mark.xfail(strict=True, reason="the tool calls a store method that does not exist")


@BROKEN
def test_create_puts_a_notification_in_the_store(tools: dict[str, Any]) -> None:
    created = _call(tools, "notifications_create", store_path="mine.sqlite", type="task.done", title="T", body="B")
    assert created.ok, created.error


@BROKEN
def test_list_shows_a_notification_that_is_in_the_store(tools: dict[str, Any], folder: Path) -> None:
    from thomas.notifications.store import NotificationCreate, NotificationStore

    NotificationStore(str(folder / "mine.sqlite")).add("n1", NotificationCreate(type="t", title="T", body="B"))
    listed = _call(tools, "notifications_list", store_path="mine.sqlite")
    assert listed.ok, listed.error


@BROKEN
def test_clear_empties_the_store(tools: dict[str, Any]) -> None:
    cleared = _call(tools, "notifications_clear", store_path="mine.sqlite")
    assert cleared.ok, cleared.error


@BROKEN
def test_mark_read_with_no_number_marks_them_all(tools: dict[str, Any]) -> None:
    marked = _call(tools, "notifications_mark_read", store_path="mine.sqlite")
    assert marked.ok, marked.error


def test_a_folder_inside_the_folder_is_made_for_the_store(tools: dict[str, Any], folder: Path) -> None:
    assert _call(tools, "notifications_get_store", store_path="deeper/mine.sqlite").ok
    assert (folder / "deeper" / "mine.sqlite").is_file()


def test_an_absolute_name_inside_the_folder_is_taken(tools: dict[str, Any], folder: Path) -> None:
    assert _call(tools, "notifications_get_store", store_path=str(folder / "abs.sqlite")).ok
    assert (folder / "abs.sqlite").is_file()


@pytest.mark.parametrize("args", [{}, {"store_path": ""}, {"store_path": "   "}, {"store_path": 7}])
def test_a_missing_name_is_refused_and_says_what_is_wanted(tools: dict[str, Any], args: dict[str, Any]) -> None:
    """Straight to ``execute``, which is what a call reaches once its arguments have passed the schema."""
    refused = _run(tools["notifications_get_store"].execute(args))
    assert not refused.ok
    assert "must name a database file" in refused.error


def _outside_names(folder: Path) -> list[str]:
    outside = folder.parent / "outside.sqlite"
    names = [
        "../outside.sqlite",
        "a/../../outside.sqlite",
        "..\\outside.sqlite",
        str(outside),
        str(outside.parent / "x" / "outside.sqlite"),
    ]
    if os.name == "nt":
        other = "D:" if folder.drive.upper() != "D:" else "E:"
        names += [
            "\\\\attacker.invalid\\share\\n.sqlite",
            "//attacker.invalid/share/n.sqlite",
            "\\\\?\\UNC\\attacker.invalid\\share\\n.sqlite",
            "\\\\.\\pipe\\n.sqlite",
            "\\??\\C:\\Windows\\Temp\\n.sqlite",
            f"{other}\\n.sqlite",
            f"{other}/n.sqlite",
            f"{other}n.sqlite",
        ]
    return names


@pytest.mark.parametrize("tool", ["notifications_get_store", "notifications_create", "notifications_list"])
def test_a_name_that_leaves_the_folder_is_refused_and_nothing_is_made(
    tools: dict[str, Any], folder: Path, tool: str
) -> None:
    before = sorted(path.name for path in folder.parent.iterdir())
    for name in _outside_names(folder):
        args = {"store_path": name, "type": "t", "title": "t", "body": "b"}
        refused = _run(tools[tool].safe_execute(args))
        assert not refused.ok, name
        assert "leaves the notifications folder" in refused.error, (name, refused.error)
    assert sorted(path.name for path in folder.parent.iterdir()) == before
    assert list(folder.iterdir()) == []


def test_another_drive_and_a_network_name_are_refused_from_the_text_before_anything_touches_the_disk(
    tools: dict[str, Any], folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scope resolves, SQLite connects and the store makes folders: none may be reached for these names."""
    touched: list[str] = []
    names = [name for name in _outside_names(folder) if name.startswith(("\\\\", "//", "\\??", "D:", "E:"))]
    if os.name != "nt":
        names = ["../outside.sqlite"]
    assert names

    def trip(label: str) -> Any:
        def tripped(*_a: Any, **_k: Any) -> Any:
            touched.append(label)
            raise AssertionError(label)

        return tripped

    monkeypatch.setattr(Scope, "resolve", trip("scope.resolve"))
    monkeypatch.setattr(Path, "resolve", trip("Path.resolve"))
    monkeypatch.setattr(sqlite3, "connect", trip("sqlite3.connect"))
    monkeypatch.setattr(os, "makedirs", trip("os.makedirs"))
    monkeypatch.setattr(store_module.NotificationStore, "__init__", trip("NotificationStore"))
    for name in names:
        refused = _run(tools["notifications_get_store"].safe_execute({"store_path": name}))
        assert not refused.ok and "leaves the notifications folder" in refused.error, name
    assert touched == []


def _link(target: Path, at: Path) -> bool:
    """A junction on Windows, which needs no privilege, and a symlink elsewhere. False if neither could be made."""
    if os.name == "nt":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(at), str(target)], capture_output=True, text=True)
        return made.returncode == 0
    try:
        os.symlink(target, at, target_is_directory=True)
    except OSError:
        return False
    return True


def test_a_link_inside_the_folder_that_leads_out_is_refused(tools: dict[str, Any], folder: Path) -> None:
    elsewhere = folder.parent / "elsewhere"
    elsewhere.mkdir()
    if not _link(elsewhere, folder / "door"):
        pytest.skip("this account may not make a link")
    refused = _call(tools, "notifications_create", store_path="door/n.sqlite", type="t", title="t", body="b")
    assert not refused.ok and "leaves the notifications folder" in refused.error
    assert list(elsewhere.iterdir()) == []


def test_a_symlink_to_a_file_outside_is_refused(tools: dict[str, Any], folder: Path) -> None:
    outside = folder.parent / "real.sqlite"
    outside.write_bytes(b"")
    try:
        os.symlink(outside, folder / "file.sqlite")
    except OSError:
        pytest.skip("this account may not make a symlink")
    refused = _call(tools, "notifications_get_unread_count", store_path="file.sqlite")
    assert not refused.ok and "leaves the notifications folder" in refused.error
    assert outside.read_bytes() == b""
