"""What the Praxis row's tests share: a server with the row on, a run opened through the real launch, and a journal folder.

No assert here, because pytest rewrites asserts only in a test module.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from thomas.server import app_core
from thomas.server.app_keys import APP_PRAXIS_RUN_CHANNELS
from thomas.server.praxis import launch, startup
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

OFF = "/api/plugins/thomas/praxis/off"
ON = "/api/plugins/thomas/praxis/on"
SETTINGS = SimpleNamespace(family="gpt", model_id="gpt-5.6-sol", reviewer_model="", dispatch_model="codex:gpt")


def journal_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices and the run journal each get a folder of this test's own."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setattr(launch, "user_praxis_root", lambda: tmp_path / "journal")
    monkeypatch.setattr(startup, "user_praxis_root", lambda: tmp_path / "journal")
    (tmp_path / "project").mkdir()
    return tmp_path


def row_of(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "praxis")


def runner_that_waits(_app: Any, _project: Path, _settings: Any, _run_id: str) -> Any:
    async def child(_id: str, _kind: str, _title: str, _brief: str, _choice: Any = None) -> Any:
        await asyncio.Event().wait()
        yield {"type": "done"}

    return child


def runner_that_finishes(seen: list[str]) -> Any:
    def make(_app: Any, _project: Path, _settings: Any, _run_id: str) -> Any:
        async def child(child_id: str, _kind: str, _title: str, _brief: str, _choice: Any = None) -> Any:
            seen.append(child_id)
            yield {"type": "done"}

        return child

    return make


async def server_with_the_row_on(root: Path) -> TestClient:
    client = TestClient(TestServer(app_core.create_app(views.config_in(root))))
    await client.start_server()
    await views.until(lambda: row_of(client.app)["state"] == "active")
    return client


def open_run(app: web.Application, root: Path, run_id: str = "r1") -> Any:
    """Open a run's channel as a Build start does, and hand back the channel."""
    launch.prepare_launch(app, SETTINGS, root / "project", run_id, "request", {}, 8899, conversation_id="conv-1")
    return app[APP_PRAXIS_RUN_CHANNELS]._runs[run_id]


async def call_status(client: TestClient, channel: Any) -> int:
    answer = await client.post(
        f"/api/praxis/run/{channel.run_id}/status", json={}, headers={"X-Thomas-Run-Token": channel.token}
    )
    return answer.status
