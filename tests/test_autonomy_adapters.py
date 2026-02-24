import json
import unittest

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.autonomy.adapters import ChatAdapter, ChatAdapterConfig


class TestAutonomyChatAdapter(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        self._last_payload = {}

        async def api_chat(request: web.Request) -> web.StreamResponse:
            payload = await request.json()
            self._last_payload = dict(payload or {})
            text = str((payload or {}).get("text") or "")

            if "fenced_json_case" in text:
                body_text = "```json\n{\"ok\": true, \"mode\": \"fenced\"}\n```"
            else:
                body_text = "{\"ok\": true, \"mode\": \"plain\"}"

            resp = web.StreamResponse(
                status=200,
                headers={"Content-Type": "application/x-ndjson; charset=utf-8"},
            )
            await resp.prepare(request)
            await resp.write(json.dumps({"type": "text", "text": body_text}).encode("utf-8") + b"\n")
            await resp.write(json.dumps({"type": "done", "ok": True}).encode("utf-8") + b"\n")
            await resp.write_eof()
            return resp

        app.router.add_post("/api/chat", api_chat)
        return app

    async def test_generate_json_parses_plain_ndjson_text(self):
        base_url = str(self.server.make_url("")).rstrip("/")
        adapter = ChatAdapter(cfg=ChatAdapterConfig(base_url=base_url, timeout_s=5.0))
        out = await adapter.generate_json(
            schema_hint={"type": "object"},
            session_id="sid_plain",
            system_prompt="You are strict JSON only.",
            user_prompt="plain_json_case",
            profile="local",
        )
        self.assertIsInstance(out, dict)
        self.assertIs(out.get("ok"), True)
        self.assertEqual(str(out.get("mode") or ""), "plain")
        self.assertEqual(str(self._last_payload.get("text") or ""), "plain_json_case")
        self.assertEqual(str(self._last_payload.get("profile") or ""), "local")

    async def test_generate_json_parses_fenced_json(self):
        base_url = str(self.server.make_url("")).rstrip("/")
        adapter = ChatAdapter(cfg=ChatAdapterConfig(base_url=base_url, timeout_s=5.0))
        out = await adapter.generate_json(
            schema_hint={"type": "object"},
            session_id="sid_fenced",
            system_prompt="JSON only.",
            user_prompt="fenced_json_case",
            profile="local",
        )
        self.assertIsInstance(out, dict)
        self.assertIs(out.get("ok"), True)
        self.assertEqual(str(out.get("mode") or ""), "fenced")


if __name__ == "__main__":
    unittest.main()
