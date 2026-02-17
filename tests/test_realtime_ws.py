import unittest
import asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

from thomas.realtime.routes import setup_realtime_routes
from thomas.realtime.config import RealtimeConfig
from thomas.realtime import keys


async def dummy_streamer(payload):
    yield {"type": "delta", "text": "hello"}
    yield {"type": "delta", "text": " world"}
    yield {"type": "done", "usage": {"input_tokens": 3, "output_tokens": 2}}


class TestRealtimeWS(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        setup_realtime_routes(app)
        self._chat_streamer = dummy_streamer

        async def _dispatch_streamer(payload):
            async for ev in self._chat_streamer(payload):
                yield ev

        app[keys.CONFIG] = RealtimeConfig(enabled=True, chat_bridge="direct")
        app[keys.CHAT_STREAMER] = _dispatch_streamer
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
        await ws.close()

    async def test_interrupt_cancels(self):
        async def slow_streamer(payload):
            yield {"type": "delta", "text": "a"}
            await asyncio.sleep(0.5)
            yield {"type": "delta", "text": "b"}
            yield {"type": "done"}

        self._chat_streamer = slow_streamer

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
