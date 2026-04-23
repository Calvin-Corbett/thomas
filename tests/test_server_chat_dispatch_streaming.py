import json
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class _FakeLLMClient:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs


class _FakeDispatchResult:
    def __init__(self, *, ok=True, execution_id="exec-123", task_id="task-123", error="") -> None:
        self.ok = ok
        self.execution_id = execution_id
        self.task_id = task_id
        self.error = error


async def _fake_stream_ack(llm, *, user_text, emit_text):  # noqa: ANN001
    _ = llm, user_text
    text = "Yeah, I'm getting started now."
    await emit_text(text)
    return text


async def _fake_dispatch(prompt, session_id, emit_event=None):  # noqa: ANN001
    _ = prompt, session_id, emit_event
    return _FakeDispatchResult()


async def _fake_watch_task(task_id, *, emit_event, **kwargs):  # noqa: ANN001
    _ = kwargs
    await emit_event({"type": "task_progress", "task_id": task_id, "text": "Worker claimed the note task."})
    await emit_event({"type": "task_complete", "task_id": task_id, "text": "Note task completed."})


class TestServerChatDispatchStreaming(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_api_chat_streams_ack_and_task_events_for_dispatch(self):
        with (
            patch("thomas.core.llm.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_aiohttp_streaming.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.agent.chat_dispatcher.dispatch_async", _fake_dispatch),
            patch("thomas.server.routes.task_events.watch_task", _fake_watch_task),
        ):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": "sess-chat-dispatch",
                    "profile": "local",
                    "mode": "auto",
                    "text": "please make a note that says verify api chat route after restart",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        self.assertIn("application/x-ndjson", str(resp.headers.get("Content-Type") or ""))
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertIn("task_dispatched", event_types)
        self.assertIn("task_progress", event_types)
        self.assertIn("task_complete", event_types)
        self.assertEqual(event_types[-1], "done")
        reply_text = "".join(str(evt.get("text") or "") for evt in events if evt.get("type") == "text")
        self.assertIn("Yeah, I'm getting started now.", reply_text)
