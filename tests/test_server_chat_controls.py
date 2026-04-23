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
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

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
        patch_event = patch_events[0]
        patch = patch_event.get("patch") or {}
        settings = patch.get("settings") or {}
        self.assertIs(settings.get("showToolDetails"), True)
        self.assertEqual(str(patch_event.get("actor") or ""), "control_parser")
        self.assertEqual(str(patch_event.get("intent_type") or ""), "ui_control")
        self.assertFalse(bool(patch_event.get("no_op", True)))
        self.assertTrue(len(patch_event.get("applied_operations") or []) >= 1)

        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        self.assertEqual(done_events[0].get("tool_calls"), 0)
        done = done_events[0]
        self.assertIn("run_usage", done)
        self.assertIn("session_usage", done)
        control_meta = (done.get("token_report") or {}).get("control") or {}
        self.assertEqual(str(control_meta.get("actor") or ""), "control_parser")
        self.assertFalse(bool(control_meta.get("no_op", True)))
        seqs = [int(e.get("seq")) for e in events]
        self.assertEqual(seqs, sorted(seqs))

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

    async def test_chat_control_accepts_sessionid_and_message_aliases(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        resp = await self.client.post(
            "/api/chat",
            json={
                "sessionId": sid,
                "profile": "local",
                "mode": "fast",
                "message": "please turn on tool details",
            },
        )
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        patch_events = [e for e in events if e.get("type") == "ui_state_patch"]
        self.assertEqual(len(patch_events), 1)
        patch = patch_events[0].get("patch") or {}
        settings = patch.get("settings") or {}
        self.assertIs(settings.get("showToolDetails"), True)

    async def test_chat_control_rejects_unknown_model_alias_profile(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        resp = await self.client.post(
            "/api/chat",
            json={
                "sessionId": sid,
                "model": "not-a-real-profile",
                "mode": "fast",
                "message": "please turn on tool details",
            },
        )
        self.assertEqual(resp.status, 400)
        text = await resp.text()
        self.assertIn("unknown profile", text)

    async def test_session_import_rejects_unknown_model_alias_profile(self):
        resp = await self.client.post(
            "/api/session/import",
            json={
                "model": "not-a-real-profile",
                "conversation": [],
            },
        )
        self.assertEqual(resp.status, 400)
        text = await resp.text()
        self.assertIn("unknown profile", text)

    async def test_chat_control_updates_batch_mode_via_stream_event(self):
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
                "text": "set mode to batch",
            },
        )
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        patch_events = [e for e in events if e.get("type") == "ui_state_patch"]
        self.assertEqual(len(patch_events), 1)
        patch = patch_events[0].get("patch") or {}
        self.assertEqual(str(patch.get("mode") or ""), "batch")

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

    async def test_chat_control_noop_reports_no_changes(self):
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
                "text": "please set mode to fast",
            },
        )
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)

        patch_events = [e for e in events if e.get("type") == "ui_state_patch"]
        self.assertEqual(len(patch_events), 1)
        patch_event = patch_events[0]
        self.assertTrue(bool(patch_event.get("no_op", False)))
        self.assertEqual(len(patch_event.get("applied_operations") or []), 0)

        text_events = [e for e in events if e.get("type") == "text"]
        self.assertEqual(len(text_events), 1)
        self.assertIn("No configuration changes were applied", str(text_events[0].get("text") or ""))

    async def test_chat_control_allows_missing_session_id_for_single_shot_payload(self):
        resp = await self.client.post(
            "/api/chat",
            json={
                "profile": "local",
                "mode": "fast",
                "message": "set mode to batch",
            },
        )
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        patch_events = [e for e in events if e.get("type") == "ui_state_patch"]
        self.assertEqual(len(patch_events), 1)
        patch = patch_events[0].get("patch") or {}
        self.assertEqual(str(patch.get("mode") or ""), "batch")


if __name__ == "__main__":
    unittest.main()
