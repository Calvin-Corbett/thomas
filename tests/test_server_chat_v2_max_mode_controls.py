"""Chat v2 per-turn controls: model, reasoning, memory and the session LLM cache."""

import unittest
from unittest.mock import patch

from tests import _chat_v2_max_mode_support as support
from tests._chat_v2_max_mode_support import _FakeBrain, _FakeDelegationStarter, _FakeLLMClient, _parse_ndjson
from thomas.server.routes import chat_v2 as chat_v2_routes


class TestServerChatV2MaxModeControls(support.ChatV2MaxModeCase):
    async def test_chat_v2_applies_reasoning_effort_from_payload(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-reasoning-low",
                    "profile": "local",
                    "mode": "auto",
                    "reasoning_effort": "low",
                    "message": "Say only hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertTrue(_FakeLLMClient.calls)
        self.assertEqual(_FakeLLMClient.calls[-1]["reasoning_effort"], "low")

    async def test_chat_v2_memory_toggle_disables_long_term_memory_for_turn(self):
        _FakeBrain.calls = []
        _FakeBrain.init_calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-memory-disabled",
                    "profile": "local",
                    "mode": "auto",
                    "memory": False,
                    "message": "Say only hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertTrue(_FakeBrain.init_calls)
        self.assertIsNone(_FakeBrain.init_calls[-1]["memory_engine"])

    async def test_chat_v2_persists_memory_off_across_later_model_turns(self):
        _FakeBrain.init_calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            first = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-memory-persisted-off",
                    "profile": "local",
                    "mode": "max",
                    "memory": False,
                    "message": "Build a small report.",
                },
            )
            second = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-memory-persisted-off",
                    "mode": "max",
                    "message": "Build another small report.",
                },
            )

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertIsNone(_FakeBrain.init_calls[-1]["memory_engine"])
        meta = await self.app[chat_v2_routes.APP_SESSION_STORE].load_meta("sess-memory-persisted-off")
        self.assertIsNotNone(meta)
        self.assertFalse(meta.memory_enabled)

    async def test_reasoning_effort_does_not_override_independent_token_economy(self):
        _FakeBrain.calls = []
        _FakeLLMClient.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-independent-settings",
                    "profile": "local",
                    "mode": "max",
                    "reasoning_effort": "xhigh",
                    "token_economy": "cheap",
                    "message": "Build a small report.",
                },
            )

        self.assertEqual(resp.status, 200)
        # The reply streams: the status arrives before the brain has been asked,
        # so read the whole turn before looking at what the brain was handed.
        await resp.text()
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(_FakeLLMClient.calls[-1]["reasoning_effort"], "xhigh")
        self.assertEqual(_FakeBrain.calls[-1]["token_economy"], "cheap")

    async def test_chat_v2_applies_model_id_from_payload(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-model-override",
                    "profile": "local",
                    "mode": "auto",
                    "model_id": "office-chat-model",
                    "message": "Say only hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertTrue(_FakeLLMClient.calls)
        self.assertEqual(_FakeLLMClient.calls[-1]["model"], "office-chat-model")
        runtime_event = next(event for event in _parse_ndjson(await resp.text()) if event["type"] == "model_runtime")
        self.assertEqual(runtime_event["runtime"]["requested"]["profile"], "local")
        self.assertEqual(runtime_event["runtime"]["active"]["model"], "office-chat-model")
        self.assertFalse(runtime_event["runtime"]["failover_used"])

    async def test_chat_v2_reuses_cached_llm_for_same_session(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            first = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Say only hello.",
                },
            )
            second = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Say only hello again.",
                },
            )

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(len(_FakeLLMClient.calls), 1)
        self.assertEqual(_FakeLLMClient.closed, [])

    async def test_chat_v2_refreshes_cached_llm_config(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            first = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache-refresh",
                    "profile": "local",
                    "mode": "auto",
                    "reasoning_effort": "low",
                    "message": "Say only hello.",
                },
            )
            second = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache-refresh",
                    "profile": "local",
                    "mode": "auto",
                    "reasoning_effort": "high",
                    "message": "Say only hello again.",
                },
            )

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(len(_FakeLLMClient.calls), 1)
        cache = self.app[chat_v2_routes.APP_SESSION_LLM_CACHE]
        entry = cache["sess-cache-refresh"]
        self.assertEqual(getattr(entry.llm.config, "reasoning_effort", ""), "high")

    async def test_chat_v2_reuses_saved_model_and_reasoning_when_later_turn_omits_them(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            first = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-saved-settings",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 4,
                    "model_id": "gpt-5.6-terra",
                    "reasoning_effort": "xhigh",
                    "message": "Say only hello.",
                },
            )
            # Simulate a process-local LLM cache miss. The durable SessionMeta,
            # rather than the first client instance, must restore the settings.
            self.app[chat_v2_routes.APP_SESSION_LLM_CACHE].clear()
            second = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-saved-settings",
                    "mode": "max",
                    "message": "Build a small text report in the background.",
                },
            )

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(len(_FakeLLMClient.calls), 2)
        self.assertEqual(_FakeLLMClient.calls[-1]["model"], "gpt-5.6-terra")
        self.assertEqual(_FakeLLMClient.calls[-1]["reasoning_effort"], "xhigh")
        self.assertEqual(_FakeDelegationStarter.calls, [])

    async def test_chat_v2_session_delete_evicts_cached_llm(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            create = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache-delete",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Say only hello.",
                },
            )
            delete = await self.client.delete("/api/v2/chat/session/sess-cache-delete")

        self.assertEqual(create.status, 200)
        self.assertEqual(delete.status, 200)
        self.assertEqual(len(_FakeLLMClient.calls), 1)
        self.assertEqual(len(_FakeLLMClient.closed), 1)
        cache = self.app[chat_v2_routes.APP_SESSION_LLM_CACHE]
        self.assertNotIn("sess-cache-delete", cache)


if __name__ == "__main__":
    unittest.main()
