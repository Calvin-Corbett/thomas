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


class _FakeModelTurn:
    reply = "Done. Implemented and verified."
    calls: list[dict[str, object]] = []


async def _fake_process_message(
    _brain,
    session_id,
    conversation,
    prompt,
    dispatcher,
    **kwargs,
):  # noqa: ANN001
    _FakeModelTurn.calls.append({"prompt": prompt, **kwargs})
    updated = conversation.append_message("user", prompt)
    await dispatcher.emit_text(_FakeModelTurn.reply)
    updated = updated.append_message(
        "assistant",
        _FakeModelTurn.reply,
        metadata={"specialists": ["reasoning"], "mode": "conversation"},
    )
    await dispatcher.emit_done(
        session_id=session_id,
        conversation_version=updated.version,
        iterations=1,
        tool_calls=0,
    )
    return updated


class TestServerTaskLedger(AioHTTPTestCase):
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
            models={
                "local": ModelConfig(name="local", model="dummy"),
                "xai": ModelConfig(
                    name="xai",
                    provider="openai_compat",
                    base_url="https://api.x.ai/v1",
                    api_key="test-key",
                    model="grok-4-1-fast-reasoning",
                    timeout_s=1,
                ),
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _new_session_id(self) -> str:
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        payload = await sess_resp.json()
        sid = str(payload.get("session_id") or "")
        self.assertTrue(sid)
        return sid

    async def test_task_ledger_current_and_history_endpoints(self):
        sid = await self._new_session_id()

        _FakeModelTurn.reply = "Done. Implemented and verified."
        _FakeModelTurn.calls = []
        with patch(
            "thomas.server.routes.chat_v2.OrchestratorBrain.process_message",
            _fake_process_message,
        ):
            chat_resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "text": "Implement task ledger API",
                },
            )
        self.assertEqual(chat_resp.status, 200)
        events = _parse_ndjson(await chat_resp.text())
        self.assertTrue(any(e.get("type") == "done" for e in events))

        current_resp = await self.client.get(f"/api/task-ledger/current?session_id={sid}")
        self.assertEqual(current_resp.status, 200)
        current_payload = await current_resp.json()
        self.assertTrue(bool(current_payload.get("ok")))
        state = current_payload.get("state") or {}
        self.assertEqual(str(state.get("status") or ""), "complete")
        self.assertIn("Implement task ledger API", str(state.get("active_goal") or ""))

        latest_resp = await self.client.get("/api/task-ledger/current")
        self.assertEqual(latest_resp.status, 200)
        latest_payload = await latest_resp.json()
        self.assertEqual(str(latest_payload.get("session_id") or ""), sid)

        history_resp = await self.client.get(f"/api/task-ledger/history?session_id={sid}&limit=20")
        self.assertEqual(history_resp.status, 200)
        history_payload = await history_resp.json()
        events = history_payload.get("events") or []
        self.assertGreaterEqual(len(events), 3)
        sources = {str(item.get("source") or "") for item in events}
        self.assertIn("chat_v2.request", sources)
        self.assertIn("chat_v2.done", sources)
        self.assertNotIn("chat.route", sources)
        self.assertEqual(len(_FakeModelTurn.calls), 1)

    async def test_max_mode_prompt_does_not_synthesize_task_contract_from_words(self):
        sid = await self._new_session_id()

        _FakeModelTurn.reply = (
            "Completed and verified. I opened the page, clicked Start, and confirmed the snake visibly moves."
        )
        with patch(
            "thomas.server.routes.chat_v2.OrchestratorBrain.process_message",
            _fake_process_message,
        ):
            chat_resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "token_economy": "max",
                    "text": "Build a snake game with a visible start flow and restart button.",
                },
            )
        self.assertEqual(chat_resp.status, 200)
        events = _parse_ndjson(await chat_resp.text())
        self.assertFalse(any(e.get("type") == "task_definition" for e in events))
        self.assertFalse(any(e.get("type") == "task_evaluation" for e in events))

        current_resp = await self.client.get(f"/api/task-ledger/current?session_id={sid}")
        self.assertEqual(current_resp.status, 200)
        current_payload = await current_resp.json()
        self.assertEqual(str(current_payload.get("task_definition_status") or ""), "idle")
        self.assertEqual(current_payload.get("task_definition"), {})
        self.assertEqual(current_payload.get("task_evaluation"), {})

    async def test_task_ledger_does_not_infer_blocked_state_from_assistant_prose(self):
        sid = await self._new_session_id()

        _FakeModelTurn.reply = "I need your API key and repository URL to continue."
        with patch(
            "thomas.server.routes.chat_v2.OrchestratorBrain.process_message",
            _fake_process_message,
        ):
            chat_resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "text": "Ship this feature",
                },
            )
        self.assertEqual(chat_resp.status, 200)

        current_resp = await self.client.get(f"/api/task-ledger/current?session_id={sid}")
        self.assertEqual(current_resp.status, 200)
        state = (await current_resp.json()).get("state") or {}
        self.assertEqual(str(state.get("status") or ""), "complete")
        self.assertEqual(state.get("missing_inputs"), [])
        self.assertEqual(str(state.get("last_progress") or ""), _FakeModelTurn.reply)

    async def test_task_ledger_updates_after_batch_mode_migrates_to_model_owned_max(self):
        sid = await self._new_session_id()

        _FakeModelTurn.reply = "BATCH_LEDGER_DONE"
        with patch(
            "thomas.server.routes.chat_v2.OrchestratorBrain.process_message",
            _fake_process_message,
        ):
            chat_resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "xai",
                    "mode": "batch",
                    "text": "Run a batch operation",
                },
            )
        self.assertEqual(chat_resp.status, 200)
        events = _parse_ndjson(await chat_resp.text())
        self.assertTrue(any(e.get("type") == "done" for e in events))
        migration = [event for event in events if event.get("type") == "mode_migrated"]
        self.assertEqual(len(migration), 1)
        self.assertEqual(migration[0].get("from"), "batch")
        self.assertEqual(migration[0].get("to"), "max")

        current_resp = await self.client.get(f"/api/task-ledger/current?session_id={sid}")
        self.assertEqual(current_resp.status, 200)
        state = (await current_resp.json()).get("state") or {}
        self.assertEqual(str(state.get("status") or ""), "complete")
        self.assertIn("BATCH_LEDGER_DONE", str(state.get("last_progress") or ""))

        history_resp = await self.client.get(f"/api/task-ledger/history?session_id={sid}&limit=20")
        self.assertEqual(history_resp.status, 200)
        history_events = (await history_resp.json()).get("events") or []
        sources = {str(item.get("source") or "") for item in history_events}
        self.assertIn("chat_v2.request", sources)
        self.assertIn("chat_v2.done", sources)
        self.assertNotIn("chat.route", sources)

    async def test_task_ledger_updates_after_swarm_mode_migrates_to_model_owned_max(self):
        sid = await self._new_session_id()

        _FakeModelTurn.reply = "SWARM_LEDGER_DONE"
        with patch(
            "thomas.server.routes.chat_v2.OrchestratorBrain.process_message",
            _fake_process_message,
        ):
            chat_resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "Run swarm operation",
                },
            )
        self.assertEqual(chat_resp.status, 200)
        events = _parse_ndjson(await chat_resp.text())
        self.assertTrue(any(e.get("type") == "done" for e in events))
        migration = [event for event in events if event.get("type") == "mode_migrated"]
        self.assertEqual(len(migration), 1)
        self.assertEqual(migration[0].get("from"), "swarm")
        self.assertEqual(migration[0].get("to"), "max")

        current_resp = await self.client.get(f"/api/task-ledger/current?session_id={sid}")
        self.assertEqual(current_resp.status, 200)
        state = (await current_resp.json()).get("state") or {}
        self.assertEqual(str(state.get("status") or ""), "complete")
        self.assertIn("SWARM_LEDGER_DONE", str(state.get("last_progress") or ""))

        history_resp = await self.client.get(f"/api/task-ledger/history?session_id={sid}&limit=20")
        self.assertEqual(history_resp.status, 200)
        history_events = (await history_resp.json()).get("events") or []
        sources = {str(item.get("source") or "") for item in history_events}
        self.assertIn("chat_v2.request", sources)
        self.assertIn("chat_v2.done", sources)
        self.assertNotIn("chat.route", sources)


if __name__ == "__main__":
    unittest.main()
