"""Queue routes stay responsive while another thread holds the shared lock.

The routes are the ones ``thomas.server.rows.project_queue`` registers; this builds its own app and calls the registrar.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from tests.test_a_thomas_project_starts_without_chat import ASK, CLAUDE, _client, w  # noqa: F401
from thomas.server import self_project_queue
from thomas.server.capacity_ledger_locks import locked


@pytest.mark.parametrize("method", ["post", "get"])
def test_route_lock_does_not_block_event_loop(w, method):
    async def scenario():
        client = await _client(w)
        acquired, release = threading.Event(), threading.Event()
        file = self_project_queue.path(w.catalog)

        def hold():
            with locked(file.parent, file.name):
                acquired.set()
                release.wait(5)

        holder = threading.Thread(target=hold)
        holder.start()
        try:
            assert await asyncio.to_thread(acquired.wait, 2)
            if method == "post":
                request = client.post("/api/self/projects/queue", json={"request": ASK, "settings": CLAUDE})
            else:
                request = client.get("/api/self/projects/queue")
            task = asyncio.create_task(request)
            await asyncio.wait_for(asyncio.sleep(0.02), 0.5)
            assert not task.done()
            release.set()
            response = await asyncio.wait_for(task, 3)
            assert response.status in (200, 201, 202)
        finally:
            release.set()
            await asyncio.to_thread(holder.join, 3)
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["post", "get"])
def test_busy_queue_route_has_sentence(w, monkeypatch, method):
    async def scenario():
        client = await _client(w)
        try:

            def busy(*args, **kwargs):
                raise PermissionError("busy")

            monkeypatch.setattr(self_project_queue, "enqueue" if method == "post" else "read", busy)
            if method == "post":
                response = await client.post("/api/self/projects/queue", json={"request": ASK, "settings": CLAUDE})
            else:
                response = await client.get("/api/self/projects/queue")
            assert response.status == 503
            assert "queue is busy" in (await response.json())["error"]
        finally:
            await client.close()

    asyncio.run(scenario())
