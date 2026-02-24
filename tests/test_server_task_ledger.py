import json
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.events import AgentEvent, EventType
from thomas.models.batching import BatchSubmission
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
                "route": {"path": "coding_task", "confidence": 1.0},
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


class _FakeBatchClientTaskLedger:
    def __init__(self, _model_cfg):
        self._closed = False

    async def close(self):
        self._closed = True

    async def create_and_add_chat_requests(self, *, batch_name, requests):
        _ = batch_name
        _ = requests
        return BatchSubmission(
            batch_id="batch_ledger_123",
            request_id="req_ledger_123",
            create_payload={"batch_id": "batch_ledger_123"},
            add_payload={},
        )

    async def get_batch(self, *, batch_id):
        _ = batch_id
        return {
            "batch_id": "batch_ledger_123",
            "state": {
                "num_requests": 1,
                "num_pending": 0,
                "num_success": 1,
                "num_error": 0,
                "num_cancelled": 0,
            },
        }

    async def list_batch_results(self, *, batch_id, limit=200, pagination_token=""):
        _ = batch_id
        _ = limit
        _ = pagination_token
        return {
            "results": [
                {
                    "batch_request_id": "req_ledger_123",
                    "response": {
                        "completion_response": {
                            "choices": [{"message": {"content": "BATCH_LEDGER_DONE"}}]
                        }
                    },
                }
            ]
        }


class _FakeSwarmOrchestratorTaskLedger:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def astream(self, *, user_request, subagents):  # noqa: ANN001
        _ = user_request
        _ = subagents
        yield {
            "type": "swarm_done",
            "ok": True,
            "final": "SWARM_LEDGER_DONE",
            "summary": {"status": {"planner": "done", "coder": "done"}},
            "duration_ms": 8,
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        }


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

        _FakeAgentLoopTaskLedger.done_text = "Done. Implemented and verified."
        _FakeAgentLoopTaskLedger.done_token_report = {"rules_of_road": {"passed": True}}
        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopTaskLedger):
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

    async def test_task_ledger_marks_blocked_when_missing_input_is_detected(self):
        sid = await self._new_session_id()

        _FakeAgentLoopTaskLedger.done_text = "I need your API key and repository URL to continue."
        _FakeAgentLoopTaskLedger.done_token_report = {"rules_of_road": {"passed": True}}
        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopTaskLedger):
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

        with patch("thomas.server.app.OpenAICompatBatchClient", _FakeBatchClientTaskLedger):
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
        self.assertIn("Batch mode run completed", str(state.get("last_progress") or ""))

        history_resp = await self.client.get(f"/api/task-ledger/history?session_id={sid}&limit=20")
        self.assertEqual(history_resp.status, 200)
        history_events = (await history_resp.json()).get("events") or []
        sources = {str(item.get("source") or "") for item in history_events}
        self.assertIn("chat.batch", sources)
        self.assertIn("chat.batch_done", sources)

    async def test_task_ledger_updates_for_swarm_mode_completion(self):
        sid = await self._new_session_id()

        with patch("thomas.server.swarm_mode.SwarmOrchestrator", _FakeSwarmOrchestratorTaskLedger):
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
        self.assertTrue(any(e.get("type") == "swarm_done" for e in events))

        current_resp = await self.client.get(f"/api/task-ledger/current?session_id={sid}")
        self.assertEqual(current_resp.status, 200)
        state = (await current_resp.json()).get("state") or {}
        self.assertEqual(str(state.get("status") or ""), "complete")
        self.assertIn("SWARM_LEDGER_DONE", str(state.get("last_progress") or ""))

        history_resp = await self.client.get(f"/api/task-ledger/history?session_id={sid}&limit=20")
        self.assertEqual(history_resp.status, 200)
        history_events = (await history_resp.json()).get("events") or []
        sources = {str(item.get("source") or "") for item in history_events}
        self.assertIn("chat.swarm", sources)
        self.assertIn("chat.swarm_done", sources)


if __name__ == "__main__":
    unittest.main()
