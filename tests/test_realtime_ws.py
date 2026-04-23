import asyncio
import unittest

from aiohttp import web
from aiohttp.client_exceptions import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from thomas.marketplace.realtime import keys
from thomas.marketplace.realtime.config import RealtimeConfig
from thomas.marketplace.realtime.routes import setup_realtime_routes


async def dummy_streamer(payload):
    yield {"type": "delta", "text": "hello"}
    yield {"type": "delta", "text": " world"}
    yield {"type": "done", "usage": {"input_tokens": 3, "output_tokens": 2}}


class TestRealtimeWS(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        setup_realtime_routes(app)
        app[keys.CONFIG] = RealtimeConfig(enabled=True, chat_bridge="direct")
        app[keys.CHAT_STREAMER] = dummy_streamer
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def _recv_until(self, ws, want_t: str, timeout=2):
        while True:
            msg = await ws.receive_json(timeout=timeout)
            if msg.get("t") == want_t:
                return msg

    async def test_ws_text_roundtrip(self):
        ws = await self.client.ws_connect("/api/realtime/ws")
        _ = await self._recv_until(ws, "ready")

        await ws.send_json({"t": "hello", "mode": "balanced", "client": {"ua": "test", "tz": "UTC"}})
        await self._recv_until(ws, "metrics")

        await ws.send_json({"t": "text", "text": "hi"})
        _ = await self._recv_until(ws, "intent")

        await self._recv_until(ws, "assistant_delta")
        await self._recv_until(ws, "assistant_delta")
        done = await self._recv_until(ws, "assistant_done")
        self.assertEqual(done["t"], "assistant_done")
        final_metrics = None
        while True:
            msg = await ws.receive_json(timeout=2)
            if msg.get("t") != "metrics":
                continue
            turns = (msg.get("state") or {}).get("turns") or []
            if turns and turns[-1].get("role") == "assistant":
                final_metrics = msg
                break
        self.assertIsNotNone(final_metrics)
        self.assertEqual(final_metrics["state"]["turns"][-1]["text"], "hello world")
        await ws.close()

    async def test_interrupt_cancels(self):
        async def slow_streamer(payload):
            yield {"type": "delta", "text": "a"}
            await asyncio.sleep(0.5)
            yield {"type": "delta", "text": "b"}
            yield {"type": "done"}

        # Avoid aiohttp started-app mutation warning by writing directly to state.
        self.server.app._state[keys.CHAT_STREAMER] = slow_streamer  # type: ignore[attr-defined]

        ws = await self.client.ws_connect("/api/realtime/ws")
        _ = await self._recv_until(ws, "ready")

        await ws.send_json({"t": "hello", "mode": "balanced", "client": {"ua": "test", "tz": "UTC"}})
        await self._recv_until(ws, "metrics")

        await ws.send_json({"t": "text", "text": "hi"})
        await self._recv_until(ws, "intent")
        await self._recv_until(ws, "assistant_delta")

        await ws.send_json({"t": "interrupt", "reason": "barge_in"})
        done = await self._recv_until(ws, "assistant_done")
        self.assertTrue(done["quality"]["canceled"])
        await ws.close()


def _require_bearer_token(request: web.Request) -> None:
    if request.headers.get("Authorization") != "Bearer test-token":
        raise web.HTTPUnauthorized(text="missing api token")


class TestRealtimeWSAuth(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        setup_realtime_routes(app, require_api_access=_require_bearer_token)
        app[keys.CONFIG] = RealtimeConfig(enabled=True, chat_bridge="http")

        async def chat_endpoint(request: web.Request) -> web.StreamResponse:
            _require_bearer_token(request)
            resp = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
            await resp.prepare(request)
            await resp.write(b'data: {"type":"assistant_delta","text":"ok"}\n\n')
            await resp.write(b'data: {"type":"assistant_done","usage":{"input_tokens":1,"output_tokens":1}}\n\n')
            await resp.write_eof()
            return resp

        app.router.add_post("/api/chat", chat_endpoint)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def _recv_until(self, ws, want_t: str, timeout=2):
        while True:
            msg = await ws.receive_json(timeout=timeout)
            if msg.get("t") == want_t:
                return msg

    async def test_ws_requires_token(self):
        with self.assertRaises(WSServerHandshakeError) as ctx:
            await self.client.ws_connect("/api/realtime/ws")
        self.assertEqual(ctx.exception.status, 401)

    async def test_ws_authorized_and_http_bridge_forwards_token(self):
        ws = await self.client.ws_connect(
            "/api/realtime/ws",
            headers={"Authorization": "Bearer test-token"},
        )
        _ = await self._recv_until(ws, "ready")
        await ws.send_json({"t": "hello", "mode": "balanced", "client": {"ua": "test", "tz": "UTC"}})
        await self._recv_until(ws, "metrics")
        await ws.send_json({"t": "text", "text": "hello"})
        _ = await self._recv_until(ws, "intent")
        delta = await self._recv_until(ws, "assistant_delta")
        self.assertEqual(delta.get("text"), "ok")
        done = await self._recv_until(ws, "assistant_done")
        self.assertEqual(done["t"], "assistant_done")
        await ws.close()
