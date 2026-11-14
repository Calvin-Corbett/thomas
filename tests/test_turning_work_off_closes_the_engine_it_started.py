"""The work row owns the autonomy engine Mission starts on first use, and ends it when the row stops.

Proofs of ``thomas.server.rows.work``, whose routes are in ``thomas.server.routes.mission`` and whose engine is built by
``thomas.server.routes.mission_autonomy_runtime``. The routes themselves are in
``tests/test_turning_work_off_touches_only_its_routes.py``. Here: off stops the engine and closes the store it started
and takes both keys away, turning it on builds new ones and never reuses a closed store, an engine the server installed
itself is left running, and a page holding the live stream open does not hold the off switch.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests import plugin_view_fixture as views
from tests.work_row_fixture import BOOTSTRAP, OFF, ON, is_closed, own_folder, row_of, server_with_the_row_on


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return own_folder(tmp_path, monkeypatch)


server = server_with_the_row_on


def test_off_stops_the_engine_it_started_closes_the_store_and_takes_the_keys_away(folder: Path) -> None:
    async def scenario() -> None:
        client = await server(folder)
        try:
            assert "autonomy_engine" not in client.app and "autonomy_store" not in client.app
            assert (await client.post(BOOTSTRAP)).status == 200
            engine, store = client.app["autonomy_engine"], client.app["autonomy_store"]
            assert engine.is_running and not is_closed(store)

            assert (await asyncio.wait_for(client.post(OFF), timeout=30)).status == 200
            assert row_of(client.app)["state"] == "off"
            assert not engine.is_running
            assert is_closed(store)
            assert "autonomy_engine" not in client.app and "autonomy_store" not in client.app
            assert "autonomy_policy" not in client.app
        finally:
            await client.close()

    asyncio.run(scenario())


def test_turning_it_on_again_builds_a_new_store_and_never_reuses_the_closed_one(folder: Path) -> None:
    async def scenario() -> None:
        client = await server(folder)
        try:
            assert (await client.post(BOOTSTRAP)).status == 200
            first_engine, first_store = client.app["autonomy_engine"], client.app["autonomy_store"]
            await asyncio.wait_for(client.post(OFF), timeout=30)
            assert (await asyncio.wait_for(client.post(ON), timeout=30)).status == 200
            await views.until(lambda: row_of(client.app)["state"] == "active")

            assert (await client.get("/api/mission/jobs")).status == 200
            assert (await client.post(BOOTSTRAP)).status == 200
            engine, store = client.app["autonomy_engine"], client.app["autonomy_store"]
            assert engine is not first_engine and store is not first_store
            assert engine.is_running and not is_closed(store)
            assert (await client.get("/api/mission/jobs")).status == 200
        finally:
            await client.close()

    asyncio.run(scenario())


class Installed:
    """What the server's own install of the engine leaves on the app, which turning the row off must not touch."""

    is_running = True
    ended: list[str] = []

    async def stop(self) -> None:
        self.ended.append("engine")

    def close(self) -> None:
        self.ended.append("store")


def test_an_engine_the_server_installed_itself_is_left_running(folder: Path) -> None:
    """Pinned with stand-ins: the server's own install (``THOMAS_AUTONOMY_ENABLED``) does not get as far as a start."""

    async def scenario() -> None:
        client = await server(folder)
        try:
            engine = store = Installed()
            client.app._state["autonomy_engine"], client.app._state["autonomy_store"] = engine, store
            assert (await client.post(BOOTSTRAP)).status == 200
            assert (await asyncio.wait_for(client.post(OFF), timeout=30)).status == 200
            assert row_of(client.app)["state"] == "off"
            assert client.app["autonomy_engine"] is engine and client.app["autonomy_store"] is store
            assert Installed.ended == []
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_page_holding_the_live_stream_open_does_not_hold_the_off_switch(folder: Path) -> None:
    async def scenario() -> None:
        client = await server(folder)
        try:
            stream = await client.get("/api/mission/stream?interval=1")
            assert stream.status == 200
            await stream.content.readany()
            assert (await asyncio.wait_for(client.post(OFF), timeout=20)).status == 200
            assert row_of(client.app)["state"] == "off"
            assert (await client.get("/api/mission/stream")).status == 404
            stream.close()
        finally:
            await client.close()

    asyncio.run(scenario())


def test_the_mission_page_still_loads_with_the_row_off(folder: Path) -> None:
    """The page belongs to the server. Its routes are the row's, so with it off the page loads and its asks get 404."""

    async def scenario() -> None:
        client = await server(folder)
        try:
            page = await client.get("/mission")
            assert page.status == 200 and 'id="missionApp"' in await page.text()
            assert (await asyncio.wait_for(client.post(OFF), timeout=30)).status == 200
            page = await client.get("/mission")
            assert page.status == 200 and 'id="missionApp"' in await page.text()
            assert (await client.get("/api/mission/control")).status == 404
        finally:
            await client.close()

    asyncio.run(scenario())
