"""The workspace row's own work: a database it opens, a scan it may be running, and a value a module keeps.

These are the proofs of ``thomas.server.rows.workspace`` for the three things a 404 cannot show. The workspaces database
opens in a worker thread in a startup step, so a row turned on in a running server does not stop it answering. A scan that
rebuilds the list of projects is cancelled by a stop. The notes runtime lives on a module, which stays loaded, so a stop
clears it. With the row off, Chat and the workspace specialist still take the registry lock, which a key on the app no
longer provides. The routes are ``thomas.server.workspace.router``, ``thomas.server.routes.local_projects_aiohttp`` and
``thomas.server.routes.source_annotation_routes``.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from thomas.server import app_core
from thomas.server.routes import local_projects_aiohttp, source_annotation_routes
from thomas.server.routes.local_project_workspace import build_project_chat_context
from thomas.server.routes.local_projects_registry import CATALOGUE_CACHE_KEY, REGISTRY_LOCK_KEY, registry_lock
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS
from thomas.server.workspace import router as workspace_router

OFF = "/api/plugins/thomas/workspace/off"
ON = "/api/plugins/thomas/workspace/on"


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    return tmp_path / "data"


@pytest.fixture(autouse=True)
def no_notes_runtime_left_behind() -> Any:
    """The runtime is a module value, so a test that builds one must not leave it for the next."""
    source_annotation_routes.reset_source_annotation_runtime()
    yield
    source_annotation_routes.reset_source_annotation_runtime()


def _row(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "workspace")


def test_the_database_opens_in_a_worker_thread_and_closes_when_the_row_stops(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened_on: list[int] = []
    real_connect = workspace_router.connect

    def connect_and_note(db_path: Path) -> sqlite3.Connection:
        opened_on.append(threading.get_ident())
        return real_connect(db_path)

    monkeypatch.setattr(workspace_router, "connect", connect_and_note)

    async def scenario() -> None:
        loop_thread = threading.get_ident()
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            assert _row(app)["state"] == "active", _row(app)
            assert (await client.get("/api/workspaces")).status == 200
            con = app[workspace_router.APP_WORKSPACE_CON]
            assert opened_on == [opened_on[0]] and opened_on[0] != loop_thread

            assert (await client.post(OFF)).status == 200

            assert workspace_router.APP_WORKSPACE_CON not in app
            with pytest.raises(sqlite3.ProgrammingError):
                con.execute("select 1")  # closed by the row's stop
            assert (await client.get("/api/workspaces")).status == 404

            assert (await client.post(ON)).status == 200
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            assert (await client.get("/api/workspaces")).status == 200
            assert len(opened_on) == 2 and opened_on[1] != loop_thread

    asyncio.run(scenario())
    assert (tmp_path / "memory" / ".thomas" / "workspaces.sqlite3").is_file()


def test_a_scan_of_the_projects_still_going_is_cancelled_by_a_stop_and_the_keys_go(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the stop step the task outlives the row, and this test sees it still pending."""
    began = threading.Event()
    release = threading.Event()

    def a_slow_scan(_app: Any) -> list[dict[str, Any]]:
        began.set()
        release.wait(60)
        return []

    monkeypatch.setattr(local_projects_aiohttp, "_build_projects_catalogue", a_slow_scan)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        try:
            async with TestClient(TestServer(app)) as client:
                await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
                listed = await client.get("/api/local/projects")
                assert listed.status == 200
                assert (await listed.json())["refreshing"] is True
                assert await asyncio.to_thread(began.wait, 30)
                task = app[CATALOGUE_CACHE_KEY]["task"]
                assert task is not None and not task.done()

                assert (await asyncio.wait_for(client.post(OFF), timeout=60)).status == 200

                assert task.cancelled()
                assert _row(app)["state"] == "off"
                assert CATALOGUE_CACHE_KEY not in app
                assert REGISTRY_LOCK_KEY not in app
        finally:
            release.set()  # the worker thread cannot be ended, and the loop waits for it on the way out

    asyncio.run(scenario())


def test_the_notes_runtime_is_built_with_the_row_and_cleared_when_it_stops(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            first = source_annotation_routes._RUNTIME
            assert first is not None
            assert source_annotation_routes.APP_SOURCE_ANNOTATION_RUNTIME in app

            assert (await client.post(OFF)).status == 200

            assert source_annotation_routes._RUNTIME is None
            assert source_annotation_routes.APP_SOURCE_ANNOTATION_RUNTIME not in app

            assert (await client.post(ON)).status == 200
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            assert source_annotation_routes._RUNTIME is not None and source_annotation_routes._RUNTIME is not first

    asyncio.run(scenario())


def test_chat_can_still_bind_a_project_with_the_row_off(tmp_path: Path, own_data_dir: Path) -> None:
    """The registry lock is a key the row writes, and Chat takes it with the row off: no KeyError, a project not found."""

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            assert (await client.post(OFF)).status == 200
            assert REGISTRY_LOCK_KEY not in app

            with pytest.raises(web.HTTPNotFound):
                await build_project_chat_context(app, project_id="p1", session_id="s1", session_store=None)

    asyncio.run(scenario())


def test_the_registry_lock_is_one_lock_for_an_app_without_the_key_and_the_keys_lock_for_one_with_it() -> None:
    bare = web.Application()
    assert registry_lock(bare) is registry_lock(bare)
    assert registry_lock(bare) is not registry_lock(web.Application())

    keyed = asyncio.Lock()
    assert registry_lock({REGISTRY_LOCK_KEY: keyed}) is keyed  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        registry_lock({})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("module", "name", "warning"),
    [
        (
            "thomas.server.routes.local_projects_aiohttp",
            "register_local_project_routes",
            "Local project routes unavailable",
        ),
        (
            "thomas.server.routes.source_annotation_routes",
            "register_source_annotation_routes",
            "Source note routes unavailable",
        ),
    ],
)
def test_a_row_that_cannot_register_reads_failed_and_not_active_with_no_routes(
    tmp_path: Path,
    own_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    module: str,
    name: str,
    warning: str,
) -> None:
    """``tests/test_server_app_routes_init.py`` pins one of the log lines, and would pass with the raise after it gone."""

    def fails(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("a reason you can read")

    real = sys.modules.get(module)
    fake = SimpleNamespace(**{name: fails})
    if real is not None:
        fake = SimpleNamespace(**{**vars(real), name: fails})
    monkeypatch.setitem(sys.modules, module, fake)
    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.workspace"):
        app = app_core.create_app(views.config_in(tmp_path))
    row = _row(app)

    assert row["state"] == "failed", row
    assert "a reason you can read" in row["error"]
    assert f"{warning}: a reason you can read" in caplog.text


def test_a_server_with_no_guards_gets_no_local_project_routes(caplog: pytest.LogCaptureFixture) -> None:
    from thomas.server.rows.workspace import plugin

    service = SimpleNamespace(require_api_access=None, require_loopback=None, read_json=None)
    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.workspace"):
        with pytest.raises(RuntimeError, match="no guards"):
            plugin.apply({"web": service}, {})

    assert "Local project route registration skipped: missing runtime dependencies" in caplog.text
