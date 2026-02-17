import json
import tempfile
import unittest

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


class TestServerChatControls(AioHTTPTestCase):
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

    async def test_chat_control_updates_settings_via_stream_event(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sess_payload = await sess_resp.json()
        sid = str(sess_payload.get("session_id") or "")
        self.assertTrue(sid)

        resp = await self.client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "profile": "local",
                "mode": "fast",
                "text": "please turn on tool details",
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.text()
        events = _parse_ndjson(body)
        self.assertTrue(events)

        patch_events = [e for e in events if e.get("type") == "ui_state_patch"]
        self.assertEqual(len(patch_events), 1)
        patch = patch_events[0].get("patch") or {}
        settings = patch.get("settings") or {}
        self.assertIs(settings.get("showToolDetails"), True)

        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        self.assertEqual(done_events[0].get("tool_calls"), 0)

    async def test_chat_control_updates_mode_via_stream_event(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sess_payload = await sess_resp.json()
        sid = str(sess_payload.get("session_id") or "")
        self.assertTrue(sid)

        resp = await self.client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "profile": "local",
                "mode": "fast",
                "text": "please set mode to thinking",
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.text()
        events = _parse_ndjson(body)
        self.assertTrue(events)

        patch_events = [e for e in events if e.get("type") == "ui_state_patch"]
        self.assertEqual(len(patch_events), 1)
        patch = patch_events[0].get("patch") or {}
        self.assertEqual(str(patch.get("mode") or ""), "thinking")

    async def test_chat_control_updates_autonomy_level_via_stream_event(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        resp = await self.client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "profile": "local",
                "mode": "fast",
                "text": "set autonomy level 4 full auto",
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.text()
        events = _parse_ndjson(body)
        self.assertTrue(events)

        patch_events = [e for e in events if e.get("type") == "ui_state_patch"]
        self.assertEqual(len(patch_events), 1)
        patch = patch_events[0].get("patch") or {}
        settings = patch.get("settings") or {}
        self.assertEqual(int(settings.get("autonomyLevel") or 0), 4)


if __name__ == "__main__":
    unittest.main()
