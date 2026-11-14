"""The workspace row leaves no open file behind: not after it is turned off and on, and not when the server closes.

Older route tests build a real app on a temporary folder with ``TestClient`` and delete the folder when they finish. On
Windows that fails with ``PermissionError`` while ``workspaces.sqlite3`` is still open. The database opens in a worker
thread in a startup step that no server waits for, so a server that closes while the file is still opening must close
what the thread opens, and a row turned off and on must close the first file before it opens the second.
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from thomas.server import app_core
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS
from thomas.server.workspace import router as workspace_router

OFF = "/api/plugins/thomas/workspace/off"
ON = "/api/plugins/thomas/workspace/on"


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    return tmp_path / "data"


def _database(tmp_path: Path) -> Path:
    return tmp_path / "memory" / ".thomas" / "workspaces.sqlite3"


def _nothing_holds_the_file(tmp_path: Path) -> None:
    """Renaming a file that is open fails on Windows, and deleting its folder fails too."""
    database = _database(tmp_path)
    assert database.is_file()
    moved = database.with_name("moved.sqlite3")
    database.replace(moved)
    moved.replace(database)
    shutil.rmtree(tmp_path / "memory")
    assert not (tmp_path / "memory").exists()


def test_off_and_on_then_a_closed_server_leaves_the_file_free(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[sqlite3.Connection] = []
    real_open = workspace_router._open_database

    def open_and_note(db_path: Any) -> sqlite3.Connection:
        con = real_open(db_path)
        opened.append(con)
        return con

    monkeypatch.setattr(workspace_router, "_open_database", open_and_note)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            assert (await client.get("/api/workspaces")).status == 200
            assert (await client.post(OFF)).status == 200
            assert (await client.post(ON)).status == 200
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            assert (await client.get("/api/workspaces")).status == 200

    asyncio.run(scenario())
    assert len(opened) == 2
    for con in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            con.execute("select 1")  # every connection it opened is closed
    _nothing_holds_the_file(tmp_path)


def test_a_server_that_closes_while_the_file_is_still_opening_leaves_it_free(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    began = threading.Event()
    release = threading.Event()
    opened: list[sqlite3.Connection] = []
    real_open = workspace_router._open_database

    def a_slow_open(db_path: Any) -> sqlite3.Connection:
        began.set()
        release.wait(30)
        con = real_open(db_path)
        opened.append(con)
        return con

    monkeypatch.setattr(workspace_router, "_open_database", a_slow_open)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        client = TestClient(TestServer(app))
        await client.start_server()
        assert await asyncio.to_thread(began.wait, 30)
        # The server closes while the worker thread is partway through opening the file.
        asyncio.get_running_loop().call_later(0.2, release.set)
        await client.close()

    asyncio.run(scenario())
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("select 1")
    _nothing_holds_the_file(tmp_path)
