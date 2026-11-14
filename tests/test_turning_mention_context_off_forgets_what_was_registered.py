"""Off forgets the threads and sessions you registered, and that is the stop hook's doing.

The routes keep what they are given on a module (``_state``), not on the app. The row builds a new state each time it turns
on, so a check on what the routes answer after off and on cannot tell whether the stop hook ran. This one reads the module.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests.plugin_view_fixture import config_in
from thomas.server import app_core
from thomas.server.routes import mention_context_routes

OFF = "/api/plugins/thomas/mention_context/off"
ON = "/api/plugins/thomas/mention_context/on"
REGISTERED = {"kind": "thread", "ref": "kept-in-memory", "content": "hello"}


@pytest.fixture(autouse=True)
def _leave_the_module_as_found() -> Any:
    mention_context_routes.reset_mention_context_state()
    yield
    mention_context_routes.reset_mention_context_state()


def test_off_clears_the_module_state_and_the_next_on_starts_with_nothing_registered(tmp_path: Path) -> None:
    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            registered = await client.post("/api/mention-context/objects", json=REGISTERED)
            held = mention_context_routes._state
            names_held = None if held is None else dict(held.threads)
            pressed_off = await client.post(OFF)
            after_off = mention_context_routes._state
            pressed_on = await client.post(ON)
            listed = await (await client.get("/api/mention-context/objects")).json()
            return {
                "registered": registered.status,
                "names_held": names_held,
                "pressed": (pressed_off.status, pressed_on.status),
                "after_off": after_off,
                "listed": listed,
            }

    found = asyncio.run(scenario())

    assert found["registered"] == 201
    assert found["names_held"] == {"kept-in-memory": "hello"}
    assert found["pressed"] == (200, 200)
    assert found["after_off"] is None
    assert "kept-in-memory" not in str(found["listed"])
