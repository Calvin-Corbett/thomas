"""What the work row's tests share: a server with the row on, its press paths, and a folder of its own to save in.

No assert here, because pytest rewrites asserts only in a test module.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from thomas.server import app_core
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

OFF = "/api/plugins/thomas/work/off"
ON = "/api/plugins/thomas/work/on"
BOOTSTRAP = "/api/mission/autopilot/bootstrap"


def row_of(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "work")


def own_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices and the autonomy store each get a folder of this test's own, whatever the machine has set."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    for name in ("THOMAS_AUTONOMY_ENABLED", "THOMAS_AUTONOMY_DB_PATH", "THOMAS_AUTONOMY_POLICY_PATH"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


async def server_with_the_row_on(root: Path) -> TestClient:
    client = TestClient(TestServer(app_core.create_app(views.config_in(root))))
    await client.start_server()
    await views.until(lambda: row_of(client.app)["state"] == "active")
    return client


def is_closed(store: Any) -> bool:
    try:
        store._conn.execute("select 1")
    except sqlite3.ProgrammingError:  # what a closed connection raises
        return True
    return False
