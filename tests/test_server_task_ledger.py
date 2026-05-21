import json
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.events import AgentEvent, EventType
from thomas.server.app import create_app


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class _FakeAgentLoopTaskLedger:
    route_path = "coding_task"
    done_text = "Done. Implemented and verified."
    done_token_report = {"rules_of_road": {"passed": True}}

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def run(self, prompt, **kwargs):  # noqa: ANN001
        _ = prompt
        mode = str(kwargs.get("mode") or "auto")
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": str(type(self).route_path), "confidence": 1.0},
                "route_input_source": "prompt_only",
                "mode": mode,
                "tools_policy": "auto",
                "autonomy_level": 3,
                "autonomy_name": "Standard",
            },
        )
        yield AgentEvent.text_delta(type(self).done_text)
        yield AgentEvent.agent_done(
            text=type(self).done_text,
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            token_report=dict(type(self).done_token_report),
        )


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

        _FakeAgentLoopTaskLedger.route_path = "coding_task"
        _FakeAgentLoopTaskLedger.done_text = "Done. Implemented and verified."
        _FakeAgentLoopTaskLedger.done_token_report = {"rules_of_road": {"passed": True}}
        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopTaskLedger):
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
        self.assertIn("chat.request", sources)
        self.assertIn("chat.route", sources)
        self.assertIn("chat.done", sources)

    async def test_task_definition_is_created_for_max_mode_task_requests(self):
        sid = await self._new_session_id()

        _FakeAgentLoopTaskLedger.route_path = "coding_task"
        _FakeAgentLoopTaskLedger.done_text = (
            "Completed and verified. I opened the page, clicked Start, and confirmed the snake visibly moves."
        )
        _FakeAgentLoopTaskLedger.done_token_report = {"rules_of_road": {"passed": True}}
        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopTaskLedger):
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
        self.assertTrue(any(e.get("type") == "task_definition" for e in events))
        self.assertTrue(any(e.get("type") == "task_evaluation" for e in events))

        current_resp = await self.client.get(f"/api/task-ledger/current?session_id={sid}")
        self.assertEqual(current_resp.status, 200)
        current_payload = await current_resp.json()
        task_definition = current_payload.get("task_definition") or {}
        task_evaluation = current_payload.get("task_evaluation") or {}
        self.assertEqual(str(current_payload.get("task_definition_status") or ""), "complete")
        self.assertEqual(str(task_definition.get("deliverable_type") or ""), "interactive_game")
        self.assertEqual(str(task_evaluation.get("status") or ""), "passed")

    async def test_task_ledger_marks_blocked_when_missing_input_is_detected(self):
        sid = await self._new_session_id()

        _FakeAgentLoopTaskLedger.route_path = "coding_task"
        _FakeAgentLoopTaskLedger.done_text = "I need your API key and repository URL to continue."
        _FakeAgentLoopTaskLedger.done_token_report = {"rules_of_road": {"passed": True}}
        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopTaskLedger):
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
        self.assertEqual(str(state.get("status") or ""), "blocked")
        missing = [str(x) for x in (state.get("missing_inputs") or [])]
        self.assertIn("API key", missing)
        self.assertIn("URL/endpoint", missing)

    async def test_task_ledger_updates_for_batch_mode_completion(self):
        sid = await self._new_session_id()

        # Batch mode bypasses AgentLoop entirely and talks to the provider
        # batch endpoint, so the AgentLoop patch alone is not enough — the
        # real OpenAICompatBatchClient would do a live HTTP POST to xAI and
        # fail with "Incorrect API key" against the test-only credentials.
        # We patch the batch client with a fake whose result body matches
        # the per-test assertion (`BATCH_LEDGER_DONE`), so the chat.done
        # ledger event records the right `last_progress`.
        from tests.test_server_batch_mode import _FakeBatchClient

        class _BatchClientWithLedgerMarker(_FakeBatchClient):
            async def list_batch_results(self, *, batch_id, limit=200, pagination_token=""):
                _ = batch_id
                _ = limit
                _ = pagination_token
                return {
                    "results": [
                        {
                            "batch_request_id": "req_test_123",
                            "response": {
                                "completion_response": {"choices": [{"message": {"content": "BATCH_LEDGER_DONE"}}]}
                            },
                        }
                    ]
                }

        _FakeAgentLoopTaskLedger.route_path = "batch_task"
        _FakeAgentLoopTaskLedger.done_text = "BATCH_LEDGER_DONE"
        _FakeAgentLoopTaskLedger.done_token_report = {"rules_of_road": {"passed": True}}
        with (
            patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopTaskLedger),
            patch("thomas.server.app.OpenAICompatBatchClient", _BatchClientWithLedgerMarker),
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

        current_resp = await self.client.get(f"/api/task-ledger/current?session_id={sid}")
        self.assertEqual(current_resp.status, 200)
        state = (await current_resp.json()).get("state") or {}
        self.assertEqual(str(state.get("status") or ""), "complete")
        self.assertIn("BATCH_LEDGER_DONE", str(state.get("last_progress") or ""))

        history_resp = await self.client.get(f"/api/task-ledger/history?session_id={sid}&limit=20")
        self.assertEqual(history_resp.status, 200)
        history_events = (await history_resp.json()).get("events") or []
        sources = {str(item.get("source") or "") for item in history_events}
        self.assertIn("chat.request", sources)
        self.assertIn("chat.route", sources)
        self.assertIn("chat.done", sources)

    async def test_task_ledger_updates_for_swarm_mode_completion(self):
        sid = await self._new_session_id()

        _FakeAgentLoopTaskLedger.route_path = "swarm"
        _FakeAgentLoopTaskLedger.done_text = "SWARM_LEDGER_DONE"
        _FakeAgentLoopTaskLedger.done_token_report = {"rules_of_road": {"passed": True}}
        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopTaskLedger):
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

        current_resp = await self.client.get(f"/api/task-ledger/current?session_id={sid}")
        self.assertEqual(current_resp.status, 200)
        state = (await current_resp.json()).get("state") or {}
        self.assertEqual(str(state.get("status") or ""), "complete")
        self.assertIn("SWARM_LEDGER_DONE", str(state.get("last_progress") or ""))

        history_resp = await self.client.get(f"/api/task-ledger/history?session_id={sid}&limit=20")
        self.assertEqual(history_resp.status, 200)
        history_events = (await history_resp.json()).get("events") or []
        sources = {str(item.get("source") or "") for item in history_events}
        self.assertIn("chat.request", sources)
        self.assertIn("chat.route", sources)
        self.assertIn("chat.done", sources)


if __name__ == "__main__":
    unittest.main()
