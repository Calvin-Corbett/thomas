"""The setup row with work still running: three routes can run for a long time, and each ends differently.

The row's words say each, and these tests hold them. A pull streams, so a stop ends it. A sync answers once, so a stop
waits, and Stop now drops its download. A repair is a process on a worker thread, so a stop waits, and Stop now cannot
reach it. The test client stays connected in each, because ``TestServer`` ends a handler when its caller hangs up and a
real server does not: a page that has given up on a repair still leaves Thomas waiting for it.

These are the proofs of ``thomas.server.rows.setup`` and ``thomas.server.routes.setup_aiohttp`` for a stop.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_proof_fixture import ROWS
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

OFF = "/api/plugins/thomas/setup/off"
WORDS = next(row for row in ROWS if row.id == "setup").config["words"]


class _SlowOllama:
    """Hands over a first line of a download and then never finishes, until the caller goes away."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.dropped = asyncio.Event()
        self.app = web.Application()
        self.app.router.add_get("/api/tags", self._tags)
        self.app.router.add_post("/api/pull", self._pull)

    async def _tags(self, _request: web.Request) -> web.Response:
        return web.json_response({"models": []})

    async def _pull(self, request: web.Request) -> web.StreamResponse:
        answer = web.StreamResponse()
        await answer.prepare(request)
        await answer.write(b'{"status": "pulling"}\n')
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.dropped.set()
        return answer


def _config_for(tmp_path: Path, ollama: TestServer) -> AppConfig:
    local = ModelConfig(name="local", model="dummy", base_url=str(ollama.make_url("/v1")))
    return AppConfig(models={"local": local}, default_model="local", memory=MemoryConfig(root=str(tmp_path / "memory")))


def _row(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "setup")


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    return tmp_path / "data"


def test_a_pull_still_streaming_is_ended_by_off_and_does_not_hold_the_switch(
    tmp_path: Path, own_data_dir: Path
) -> None:
    """Without ``streams=`` this press never ends, because the download has no end of its own here."""

    async def scenario() -> None:
        slow = _SlowOllama()
        async with TestServer(slow.app) as ollama:
            app = app_core.create_app(_config_for(tmp_path, ollama))
            async with TestClient(TestServer(app)) as client:
                pulling = await client.post("/api/local/pull", json={"model_id": "m"})
                assert pulling.status == 200
                await asyncio.wait_for(slow.started.wait(), timeout=30)

                pressed = await asyncio.wait_for(client.post(OFF), timeout=60)

                assert pressed.status == 200
                assert (await pressed.json())["state"] == "off"
                await asyncio.wait_for(slow.dropped.wait(), timeout=30)
                assert (await client.post("/api/local/pull", json={"model_id": "m"})).status == 404

    asyncio.run(scenario())


def test_the_words_say_a_download_another_program_started_stops_at_once() -> None:
    """Only Easy Setup's own download holds the switch. A pull, which other programs use, is ended by off at once."""
    off_means = WORDS["off_means"]

    assert "a model download is running when you turn this off, Thomas waits" not in off_means
    assert "a model download another program started stops at once" in off_means
    assert "a model download Easy Setup started" in off_means


def test_a_sync_holds_the_switch_until_stop_now_drops_its_download(tmp_path: Path, own_data_dir: Path) -> None:
    """The row's words say Thomas waits for a model download, and that Stop now leaves it partway."""

    async def scenario() -> None:
        slow = _SlowOllama()
        async with TestServer(slow.app) as ollama:
            app = app_core.create_app(_config_for(tmp_path, ollama))
            async with TestClient(TestServer(app)) as client:
                syncing = asyncio.create_task(client.post("/api/local/sync", json={"model_ids": ["m"]}))
                await asyncio.wait_for(slow.started.wait(), timeout=30)
                turning_off = asyncio.create_task(client.post(OFF))
                await asyncio.wait_for(views.until(lambda: _row(app)["state"] == "unloading"), timeout=30)
                await asyncio.sleep(0.2)

                assert _row(app)["waiting_for"] == 1
                assert not turning_off.done()
                assert not slow.dropped.is_set()

                assert (await client.post(f"{OFF}?force=1")).status == 200

                assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
                await asyncio.wait_for(slow.dropped.wait(), timeout=30)
                assert _row(app)["state"] == "off"
                assert _row(app)["stopped_partway"] is True
                await asyncio.gather(syncing, return_exceptions=True)  # the connection is dropped with it

    asyncio.run(scenario())


def test_a_repair_holds_the_switch_and_stop_now_leaves_it_running(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's words say Thomas waits for a repair, and that Stop now does not end one. It is a process on a thread."""
    began = threading.Event()
    finish = threading.Event()
    ended = threading.Event()
    real_run = subprocess.run

    def a_slow_repair(command: Any, *args: Any, **kwargs: Any) -> Any:
        if "repair.ps1" not in str(command):
            return real_run(command, *args, **kwargs)
        began.set()
        finish.wait(120)
        ended.set()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", a_slow_repair)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            repairing = asyncio.create_task(client.post("/api/setup/repair", json={}))
            assert await asyncio.to_thread(began.wait, 30)
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: _row(app)["state"] == "unloading"), timeout=30)
            await asyncio.sleep(0.2)

            assert _row(app)["waiting_for"] == 1
            assert not turning_off.done()

            assert (await client.post(f"{OFF}?force=1")).status == 200

            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
            assert _row(app)["state"] == "off"
            assert _row(app)["stopped_partway"] is True
            assert not ended.is_set()
            finish.set()  # before the event loop closes, because that waits for this thread
            assert await asyncio.to_thread(ended.wait, 30)
            await asyncio.gather(repairing, return_exceptions=True)  # the connection is dropped, and the script is not

    try:
        asyncio.run(scenario())
    finally:
        finish.set()
