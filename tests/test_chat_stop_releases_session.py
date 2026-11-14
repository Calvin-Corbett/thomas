"""A real HTTP Stop cancels foreground generation and unblocks the next turn."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.llm_shared import StreamEvent
from thomas.server.app import create_app
from thomas.server.app_keys import (
    APP_RUN_STORE_ENABLED,
    APP_RUN_STORE_MODULE,
    APP_SESSION_LOCKS,
    APP_SESSION_LOCKS_LOCK,
)
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE
from thomas.server.routes.chat_v2_session_guard import session_serialised


class _ProductionCancellationServer(TestServer):
    async def _make_runner(self, **kwargs):
        # TestServer silently enables a feature app_lifecycle.py does not.
        # Exercise the production AppRunner default instead of masking the bug.
        kwargs["handler_cancellation"] = False
        return await super()._make_runner(**kwargs)


class _Runs:
    def __init__(self):
        self.runs = {}

    def create_run(self, metadata):
        self.runs[metadata["run_id"]] = dict(metadata)
        return metadata["run_id"]

    def ThreadedRunWriter(self, run_id):  # noqa: N802
        class Writer:
            def start(self):
                pass

            def record(self, event):
                pass

            def close(self):
                pass

        return Writer()

    def finalize_run(self, run_id, **payload):
        self.runs[run_id].update(payload)


@pytest.mark.asyncio
async def test_http_stop_cancels_provider_saves_partial_and_releases_next_turn(tmp_path: Path, monkeypatch) -> None:
    release = asyncio.Event()
    cancelled = asyncio.Event()
    independent_done = asyncio.Event()

    class Provider:
        calls = 0

        def stream_chat(self, *, messages, tools=None):
            self.calls += 1
            first = self.calls == 1

            async def generate():
                if not first:
                    yield StreamEvent(type="token", data={"text": "Lantern is ready at 9:15 AM."})
                    yield StreamEvent(type="done", data={})
                    return
                try:
                    yield StreamEvent(type="token", data={"text": "The first sentence is visible. "})
                    yield StreamEvent(type="token", data={"text": "The next sentence is pending"})
                    await release.wait()
                    yield StreamEvent(type="done", data={})
                finally:
                    cancelled.set()

            return generate()

    provider = Provider()

    async def init_model(*args, **kwargs):
        return provider, None, "local"

    async def independent_work():
        await independent_done.wait()

    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    monkeypatch.setattr("thomas.server.routes.chat_v2.initialize_chat_v2_llm", init_model)
    config = AppConfig(
        models={
            "local": ModelConfig(
                name="local", provider="openai_compat", base_url="http://127.0.0.1:1/v1", model="offline-test"
            )
        },
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="local"),
    )
    app = create_app(config)
    runs = _Runs()
    app[APP_RUN_STORE_ENABLED] = True
    app[APP_RUN_STORE_MODULE] = runs
    client = TestClient(_ProductionCancellationServer(app))
    await client.start_server()
    background = asyncio.create_task(independent_work())
    follow_up = None
    try:
        response = await client.post(
            "/api/v2/chat",
            json={
                "session_id": "stop-proof",
                "profile": "local",
                "message": "Start a long reply",
            },
        )
        assert response.status == 200

        async def read_text():
            while True:
                line = await response.content.readline()
                assert line, "Stream ended before its first text"
                event = json.loads(line)
                if event.get("type") == "text":
                    return event["text"]

        visible = await asyncio.wait_for(read_text(), 10)
        assert "first sentence" in visible
        assert not release.is_set()
        response.close()  # Same transport disconnect as fetch AbortController.
        follow_up = asyncio.create_task(
            client.post(
                "/api/v2/chat",
                json={
                    "session_id": "stop-proof",
                    "profile": "local",
                    "message": "Reply briefly now",
                },
            )
        )
        # The old generation never receives its release signal. The new answer
        # therefore proves cancellation released the same-session request lock.
        await asyncio.wait_for(cancelled.wait(), 1)
        next_response = await asyncio.wait_for(follow_up, 2)
        events = [json.loads(line) for line in (await asyncio.wait_for(next_response.text(), 2)).splitlines()]
        answer = "".join(event.get("text", "") for event in events if event["type"] == "text")
        assert answer == "Lantern is ready at 9:15 AM."
        assert not background.done(), "Disconnect must not cancel independent delegated tasks"
        assert not release.is_set()
        conversation = await app[APP_SESSION_STORE].load("stop-proof")
        replies = [message for message in conversation.get_messages() if message["role"] == "assistant"]
        assert replies[0]["metadata"]["interrupted"] is True
        assert replies[0]["content"] == visible.strip()
        assert replies[-1]["content"] == answer
        receipts = list(runs.runs.values())
        assert len(receipts) == 2
        assert receipts[0]["ok"] is False
        assert receipts[0]["error"] == "chat turn cancelled"
        assert receipts[1]["ok"] is True
        await asyncio.sleep(0)
        assert not [task for task in asyncio.all_tasks() if task.get_name() == "chat-client-disconnect"]
    finally:
        release.set()
        independent_done.set()
        await background
        if follow_up and not follow_up.done():
            follow_up.cancel()
            await asyncio.gather(follow_up, return_exceptions=True)
        await client.close()


@pytest.mark.asyncio
async def test_disconnected_queued_request_never_runs_after_the_lock_releases() -> None:
    lock = asyncio.Lock()
    await lock.acquire()
    arrived = asyncio.Event()
    invoked = []
    app = web.Application()
    app[APP_SESSION_LOCKS] = {"queued-session": lock}
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()

    async def turn(request):
        invoked.append(True)
        return web.json_response({"ok": True})

    guarded = session_serialised(turn)

    async def route(request):
        await request.json()
        arrived.set()
        return await guarded(request)

    app.router.add_post("/chat", route)
    server = _ProductionCancellationServer(app)
    await server.start_server()
    try:
        reader, writer = await asyncio.open_connection(server.host, server.port)
        body = b'{"session_id":"queued-session"}'
        writer.write(
            b"POST /chat HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
        )
        await writer.drain()
        await asyncio.wait_for(arrived.wait(), 1)
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.15)
        lock.release()
        await asyncio.sleep(0.1)
        assert invoked == []
        assert not [task for task in asyncio.all_tasks() if task.get_name() == "chat-client-disconnect"]
    finally:
        if lock.locked():
            lock.release()
        await server.close()
