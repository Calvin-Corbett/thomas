import json
import os
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


class _FakeBatchClient:
    def __init__(self, _model_cfg):
        self._closed = False

    async def close(self):
        self._closed = True

    async def create_and_add_chat_requests(self, *, batch_name, requests):
        _ = batch_name
        _ = requests
        return BatchSubmission(
            batch_id="batch_test_123",
            request_id="req_test_123",
            create_payload={"batch_id": "batch_test_123"},
            add_payload={},
        )

    async def get_batch(self, *, batch_id):
        _ = batch_id
        return {
            "batch_id": "batch_test_123",
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
                    "batch_request_id": "req_test_123",
                    "response": {
                        "completion_response": {
                            "choices": [
                                {"message": {"content": "BATCH_MODE_OK"}}
                            ]
                        }
                    },
                }
            ]
        }


class _FakeBatchClientTimeout(_FakeBatchClient):
    async def get_batch(self, *, batch_id):
        _ = batch_id
        return {
            "batch_id": "batch_test_123",
            "state": {
                "num_requests": 1,
                "num_pending": 1,
                "num_success": 0,
                "num_error": 0,
                "num_cancelled": 0,
            },
        }


class _FakeBatchClientErrorResult(_FakeBatchClient):
    async def list_batch_results(self, *, batch_id, limit=200, pagination_token=""):
        _ = batch_id
        _ = limit
        _ = pagination_token
        return {
            "results": [
                {
                    "batch_request_id": "req_test_123",
                    "error": {"message": "provider batch failure"},
                }
            ]
        }


class _FakeAgentLoop:
    seen_modes: list[str] = []

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def run(self, prompt, *, mode="auto", tools_policy="auto", job_type=None):  # noqa: ANN001
        _ = prompt
        _ = tools_policy
        _ = job_type
        _FakeAgentLoop.seen_modes.append(str(mode))
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "general", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": "never",
                "autonomy_level": 3,
                "autonomy_name": "Standard",
            },
        )
        yield AgentEvent.text_delta("AUTO_FALLBACK_OK")
        yield AgentEvent.agent_done(
            text="AUTO_FALLBACK_OK",
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            token_report={"mode": str(mode)},
        )


class TestServerBatchMode(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        self._db_path = f"{self._tmpdir.name}\\prefs_batch_runtime.sqlite"
        os.environ["THOMAS_DB_PATH"] = self._db_path

    def tearDown(self) -> None:
        if self._prev_db_path is None:
            os.environ.pop("THOMAS_DB_PATH", None)
        else:
            os.environ["THOMAS_DB_PATH"] = self._prev_db_path
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={
                "xai": ModelConfig(
                    name="xai",
                    provider="openai_compat",
                    base_url="https://api.x.ai/v1",
                    api_key="test-key",
                    model="grok-4-1-fast-reasoning",
                    timeout_s=1,
                ),
                "codex": ModelConfig(
                    name="codex",
                    provider="codex",
                    model="codex-mini-latest",
                ),
            },
            default_model="xai",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_batch_mode_streams_done_and_text(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.app.OpenAICompatBatchClient", _FakeBatchClient):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "xai",
                    "mode": "batch",
                    "text": "run this as long horizon",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)

        route_events = [e for e in events if e.get("type") == "route"]
        self.assertEqual(len(route_events), 1)
        self.assertEqual(str(route_events[0].get("mode") or ""), "batch")

        text_events = [e for e in events if e.get("type") == "text"]
        self.assertTrue(any("BATCH_MODE_OK" in str(e.get("text") or "") for e in text_events))

        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        done = done_events[0]
        self.assertEqual(int(done.get("tool_calls") or 0), 0)
        self.assertIn("run_usage", done)
        self.assertIn("session_usage", done)
        token_report = done.get("token_report") or {}
        self.assertEqual(str(token_report.get("mode") or ""), "batch")
        self.assertIn("rules_of_road", token_report)
        self.assertIn("rules_of_road", done)
        self.assertEqual((done.get("token_economy") or {}).get("applied"), "optimal")
        self.assertEqual((token_report.get("token_economy") or {}).get("applied"), "optimal")
        seqs = [int(e.get("seq")) for e in events]
        self.assertTrue(all(v >= 0 for v in seqs))
        self.assertEqual(seqs, sorted(seqs))

    async def test_batch_mode_timeout_streams_error(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.app.OpenAICompatBatchClient", _FakeBatchClientTimeout):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "xai",
                    "mode": "batch",
                    "text": "run this as long horizon",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        err = [e for e in events if e.get("type") == "error"]
        self.assertGreaterEqual(len(err), 1)
        self.assertIn("timed out", str(err[0].get("error") or "").lower())
        done = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done), 0)

    async def test_batch_mode_result_error_streams_error(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.app.OpenAICompatBatchClient", _FakeBatchClientErrorResult):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "xai",
                    "mode": "batch",
                    "text": "run this as long horizon",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        err = [e for e in events if e.get("type") == "error"]
        self.assertGreaterEqual(len(err), 1)
        self.assertIn("provider batch failure", str(err[0].get("error") or ""))
        done = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done), 0)

    async def test_batch_mode_falls_back_to_auto_when_capability_missing(self):
        _FakeAgentLoop.seen_modes.clear()
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.app.AgentLoop", _FakeAgentLoop):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "codex",
                    "mode": "batch",
                    "text": "run this",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)

        route_events = [e for e in events if e.get("type") == "route"]
        self.assertEqual(len(route_events), 1)
        self.assertEqual(str(route_events[0].get("mode") or ""), "auto")
        self.assertIn("auto", _FakeAgentLoop.seen_modes)

        text_events = [e for e in events if e.get("type") == "text"]
        self.assertTrue(any("AUTO_FALLBACK_OK" in str(e.get("text") or "") for e in text_events))

    async def test_batch_mode_done_includes_budget_report_when_advanced_cost_enabled(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        patch_resp = await self.client.patch(
            "/api/preferences",
            json={
                "advanced": {
                    "cost": {
                        "session_token_budget": 1000,
                        "daily_token_budget": 10000,
                        "throttle_on_budget": True,
                    }
                }
            },
        )
        self.assertEqual(patch_resp.status, 200)

        with patch("thomas.server.app.OpenAICompatBatchClient", _FakeBatchClient):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "xai",
                    "mode": "batch",
                    "text": "budget test",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        budget = ((done_events[0].get("token_report") or {}).get("budget") or {})
        self.assertEqual((budget.get("session") or {}).get("budget_tokens"), 1000)
        self.assertEqual((budget.get("daily") or {}).get("budget_tokens"), 10000)


if __name__ == "__main__":
    unittest.main()
