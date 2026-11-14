"""The overlay row with a save still running: a stop waits for it, and Stop now drops the request but not the save.

The row's words say Thomas waits for a save when you turn this off, and that a save already under way finishes and is kept
even after Stop now. A save runs on a worker thread, which nothing can end, so these hold both. The save here is the real
one, held at its start until the test lets it go, so what is read afterwards is the real file.

These are the proofs of ``thomas.server.rows.overlay`` and ``thomas.server.routes.ui_overlay_routes`` for a stop.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from thomas.server import app_core
from thomas.server.overlay import manifest as m
from thomas.server.overlay import render
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

OFF = "/api/plugins/thomas/overlay/off"
RECORD = {
    "op": "set",
    "kind": "token",
    "address": "token:nebula:--c-accent",
    "value": "#2ecc71",
}
ACTION = {"actor": "test", "instruction": "save", "targets": []}


def _row(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "overlay")


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, and the saved changes in a folder of their own."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_OVERLAY_DIR", str(tmp_path / "overlay"))
    render.invalidate()
    return tmp_path / "overlay"


@pytest.fixture
def a_held_save(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Event, threading.Event]:
    """The real save, held at its start. The first event says it began, and the second lets it go."""
    began, release = threading.Event(), threading.Event()
    real = m.append

    def held(*args: Any, **kwargs: Any) -> Any:
        began.set()
        release.wait(120)
        return real(*args, **kwargs)

    monkeypatch.setattr(m, "append", held)
    yield began, release
    release.set()  # before the event loop closes, because that waits for this thread


def _saved(folder: Path) -> list[str]:
    loaded = m.load(folder / "manifest.json")
    return [] if loaded is None else [str(record["address"]) for record in loaded.records]


def test_a_save_holds_the_switch_until_it_ends(
    tmp_path: Path, own_data_dir: Path, a_held_save: tuple[threading.Event, threading.Event]
) -> None:
    began, release = a_held_save

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            saving = asyncio.create_task(
                client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [RECORD]})
            )
            assert await asyncio.to_thread(began.wait, 30)
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: _row(app)["state"] == "unloading"), timeout=30)
            await asyncio.sleep(0.2)

            assert _row(app)["waiting_for"] == 1
            assert not turning_off.done()

            release.set()

            saved = await asyncio.wait_for(saving, timeout=30)
            assert saved.status == 200
            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
            assert _row(app)["state"] == "off"
            assert _row(app)["stopped_partway"] is False
            assert _saved(own_data_dir) == ["token:nebula:--c-accent"]

    asyncio.run(scenario())


def test_stop_now_drops_the_request_and_the_save_still_finishes_and_is_kept(
    tmp_path: Path, own_data_dir: Path, a_held_save: tuple[threading.Event, threading.Event]
) -> None:
    began, release = a_held_save

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            saving = asyncio.create_task(
                client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [RECORD]})
            )
            assert await asyncio.to_thread(began.wait, 30)
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: _row(app)["state"] == "unloading"), timeout=30)

            assert (await client.post(f"{OFF}?force=1")).status == 200

            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
            assert _row(app)["state"] == "off"
            assert _row(app)["stopped_partway"] is True
            assert _saved(own_data_dir) == []  # the save has not begun to write, so nothing is half written either

            release.set()
            for _ in range(200):
                if _saved(own_data_dir):
                    break
                await asyncio.sleep(0.1)
            assert _saved(own_data_dir) == ["token:nebula:--c-accent"]
            answer = (await asyncio.gather(saving, return_exceptions=True))[0]
            # The request was dropped with the stop, so the page that sent it never hears that its save landed.
            assert isinstance(answer, BaseException) or answer.status != 200, answer
            assert json.loads((own_data_dir / "manifest.json").read_text(encoding="utf-8"))["records"]

    asyncio.run(scenario())
