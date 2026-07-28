"""POST /api/chat must always be claimed by somebody.

Chat V2 is the only registrar of ``/api/chat``. When its registration raised,
the server finished booting with the route unclaimed: the browser got a bare
404 that reads like a client bug, and the only trace was one log warning in a
console nobody had open.

Replaces (2026-07-28) the sabotage-based coverage that used to live in
``test_server_swarm_mode_telemetry`` and ``test_server_swarm_event_contract``.
Those six tests sabotaged Chat V2 registration with
``RuntimeError("legacy-chat-required")`` and then expected a legacy V1 chat
route to answer. It never could:

* ``register_chat_routes`` is called from nowhere in ``thomas/``, and its own
  docstring says production passes ``register_primary_chat=False`` so
  ``/api/chat`` "cannot execute this parallel engine";
* the swarm engine they named is gone -- ``chat_modes.maybe_handle_swarm_mode``
  imports ``thomas.server.routes.chat_swarm``, a module that does not exist;
* Chat V2 folded the mode into a token-economy alias
  (``_LEGACY_MODE_MIGRATIONS`` maps ``swarm`` -> ``max``).

The same conclusion was reached for the identical sabotage pattern in
``test_server_session_run_guard_modes.py`` (commit 7bf78836, 2026-07-22). So
the legacy fallback stays retired, and what these tests pin instead is that the
failure is loud: 503 with a named code, and a degraded health report.
"""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


def _config(root: str) -> AppConfig:
    return AppConfig(
        models={
            "local": ModelConfig(
                name="local",
                provider="openai_compat",
                base_url="http://127.0.0.1:11434/v1",
                model="local-model",
            )
        },
        default_model="local",
        memory=MemoryConfig(root=root),
        server=ServerConfig(access_mode="local"),
    )


class _BaseChatRegistrationCase(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()


class TestChatEndpointRegisteredNormally(_BaseChatRegistrationCase):
    """The good direction: a healthy boot serves real chat, not the sentinel."""

    async def get_application(self):
        return create_app(_config(self._tmpdir.name))

    async def test_chat_endpoint_is_served_by_chat_v2(self):
        # An empty message is rejected by the real V2 handler with 400. A 404
        # would mean nobody claimed the route; a 503 would mean the sentinel
        # answered instead of Chat V2.
        resp = await self.client.post("/api/chat", json={"text": ""})
        self.assertEqual(resp.status, 400)
        self.assertNotIn("chat_v2_registration_failed", await resp.text())

        v2_resp = await self.client.post("/api/v2/chat", json={"text": ""})
        self.assertEqual(v2_resp.status, 400)

    async def test_health_does_not_report_chat_as_degraded(self):
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(bool((payload.get("features") or {}).get("chat")))
        self.assertNotIn("chat", list(payload.get("degraded") or []))


class TestChatEndpointWhenChatV2FailsToRegister(_BaseChatRegistrationCase):
    """The bad direction: registration fails, and it says so instead of 404."""

    async def get_application(self):
        with patch(
            "thomas.server.routes.chat_v2.register_chat_v2_routes",
            side_effect=RuntimeError("chat-v2-boom"),
        ):
            return create_app(_config(self._tmpdir.name))

    async def test_chat_answers_503_with_a_named_cause_not_404(self):
        resp = await self.client.post("/api/chat", json={"text": "hello"})
        self.assertEqual(resp.status, 503)
        payload = await resp.json()
        self.assertEqual(payload.get("code"), "chat_v2_registration_failed")
        self.assertIn("chat-v2-boom", str(payload.get("detail") or ""))
        self.assertIn("Chat is unavailable", str(payload.get("error") or ""))

    async def test_v2_chat_alias_also_answers_503(self):
        resp = await self.client.post("/api/v2/chat", json={"text": "hello"})
        self.assertEqual(resp.status, 503)
        self.assertEqual((await resp.json()).get("code"), "chat_v2_registration_failed")

    async def test_health_reports_chat_degraded(self):
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertEqual(payload.get("status"), "degraded")
        self.assertIn("chat", list(payload.get("degraded") or []))
        self.assertIs((payload.get("features") or {}).get("chat"), False)


if __name__ == "__main__":
    unittest.main()
