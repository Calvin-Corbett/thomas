"""Chat v2 leaves dispatch to the model: no words launch background work first."""

import unittest
from unittest.mock import patch

from tests import _chat_v2_max_mode_support as support
from tests._chat_v2_max_mode_support import _FakeBrain, _FakeDelegationStarter, _parse_ndjson


class TestServerChatV2MaxModeDispatch(support.ChatV2MaxModeCase):
    async def test_auto_mode_wires_send_task_at_agent_autonomy_no_regex_launch(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto",
                    "profile": "local",
                    "mode": "auto",
                    # At L3+ the MODEL gets the send_task tool and decides whether to
                    # hand work off — organically, no regex pre-classification, no
                    # auto-launch behind its back.
                    "autonomy_level": 3,
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        # No regex-driven auto-launch: dispatch is the model's call via send_task.
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(len(_FakeDelegationStarter.calls), 0)
        self.assertEqual(len(_FakeBrain.calls), 1)
        # The send_task callback IS wired at L3 (the model can dispatch organically).
        self.assertIsNotNone(_FakeBrain.calls[0].get("send_task"))
        # Thomas also receives the bounded governed-operator callback, never the
        # raw registry. The controller itself enforces autonomy and guardrails.
        self.assertIsNotNone(_FakeBrain.calls[0].get("operate"))
        # No canned background-ack path; the prompt is unmodified (no visible-reply hack).
        self.assertFalse(bool(_FakeBrain.calls[0].get("background_ack_only", False)))
        self.assertEqual(str(_FakeBrain.calls[0].get("prompt") or ""), "please implement this plan")

    async def test_live_repo_words_do_not_force_background_dispatch(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        prompt = (
            "Development task. Work in the live Thomas repo. Locally uninstall these "
            "marketplace modules: Life Manager, Brownies, Smart Home, and Telegram Channel. "
            "Use your file tools for repo edits."
        )
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-live-repo",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 3,
                    "file_access": "project",
                    "message": prompt,
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertIsNotNone(_FakeBrain.calls[0].get("send_task"))
        self.assertEqual(_FakeBrain.calls[0].get("prompt"), prompt)

    async def test_auto_mode_low_autonomy_keeps_actionable_request_inline(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-inline",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 2,
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertNotIn("dispatch_actionable", _FakeBrain.calls[0])
        self.assertNotIn("background_ack_only", _FakeBrain.calls[0])
        self.assertEqual(str(_FakeBrain.calls[0].get("prompt") or ""), "please implement this plan")

    async def test_file_tool_words_do_not_toggle_a_hidden_actionable_route(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-tools",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Use your file tools and name three top-level files in the current repo.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertNotIn("dispatch_actionable", _FakeBrain.calls[0])

    async def test_reply_first_words_do_not_prelaunch_background_work(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-bg",
                    "profile": "local",
                    "mode": "auto",
                    "message": "answer now and delegate the rest in the background",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)

    async def test_subagent_words_do_not_prelaunch_background_work(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-explicit-delegation",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 4,
                    "message": "Spawn exactly three real sub-agents now and keep the response short.",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertEqual(
            str(_FakeBrain.calls[0].get("prompt") or ""),
            "Spawn exactly three real sub-agents now and keep the response short.",
        )

    async def test_auto_mode_chat_level_does_not_launch_explicit_subagents(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-no-delegation",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 1,
                    "message": "Spawn exactly three real sub-agents now and keep the response short.",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)

    async def test_token_economy_does_not_prelaunch_delegation(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-economy",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 4,
                    "token_economy": "max",
                    "message": "Say only hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertNotIn("delegation_started", [str(event.get("type") or "") for event in events])
        reply_text = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
        self.assertEqual(reply_text, "Thomas reply.")
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertIsNotNone(_FakeBrain.calls[0].get("send_task"))
        self.assertEqual(_FakeDelegationStarter.calls, [])

    async def test_chat_v2_max_token_economy_respects_low_autonomy_cap(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-economy-low-autonomy",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 2,
                    "token_economy": "max",
                    "message": "Compare the three options.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertEqual(_FakeDelegationStarter.calls, [])

    async def test_max_mode_controls_do_not_start_worker_without_model_call(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-worker-controls",
                    "profile": "local",
                    "mode": "max",
                    "file_access": "full",
                    "token_economy": "max",
                    "thomas_guardrails": "fortress",
                    "message": "Create a safe workspace artifact.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)


if __name__ == "__main__":
    unittest.main()
