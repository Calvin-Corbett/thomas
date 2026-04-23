import asyncio
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


class _FakeBatchClientConcurrent:
    def __init__(self, _model_cfg):
        self._closed = False

    async def close(self):
        self._closed = True

    async def create_and_add_chat_requests(self, *, batch_name, requests):
        _ = batch_name
        _ = requests
        return BatchSubmission(
            batch_id="batch_concurrency_1",
            request_id="req_concurrency_1",
            create_payload={"batch_id": "batch_concurrency_1"},
            add_payload={},
        )

    async def get_batch(self, *, batch_id):
        _ = batch_id
        await asyncio.sleep(0.03)
        return {
            "batch_id": "batch_concurrency_1",
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
                    "batch_request_id": "req_concurrency_1",
                    "response": {
                        "completion_response": {
                            "choices": [
                                {"message": {"content": "BATCH_CONCURRENT_OK"}}
                            ]
                        }
                    },
                }
            ]
        }


class _FakeFastAgentLoop:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def run(self, prompt, *, mode="auto", tools_policy="auto", job_type=None):  # noqa: ANN001
        _ = prompt
        _ = tools_policy
        _ = job_type
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
        await asyncio.sleep(0.01)
        yield AgentEvent.text_delta("FAST_CONCURRENT_OK")
        yield AgentEvent.agent_done(
            text="FAST_CONCURRENT_OK",
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            token_report={"mode": str(mode)},
        )


class TestServerMixedModeConcurrency(AioHTTPTestCase):
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
                "xai": ModelConfig(
                    name="xai",
                    provider="openai_compat",
                    base_url="https://api.x.ai/v1",
                    api_key="test-key",
                    model="grok-4-1-fast-reasoning",
                    timeout_s=1,
                ),
                "local": ModelConfig(name="local", model="dummy"),
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _new_session_id(self) -> str:
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)
        return sid

    async def test_batch_and_fast_streams_are_isolated_under_concurrency(self):
        sid_fast = await self._new_session_id()
        sid_batch = await self._new_session_id()

        async def _call_fast():
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid_fast,
                    "profile": "local",
                    "mode": "fast",
                    "text": "run fast",
                },
            )
            return resp.status, _parse_ndjson(await resp.text())

        async def _call_batch():
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid_batch,
                    "profile": "xai",
                    "mode": "batch",
                    "text": "run batch",
                },
            )
            return resp.status, _parse_ndjson(await resp.text())

        with patch("thomas.server.app.AgentLoop", _FakeFastAgentLoop), patch(
            "thomas.server.app.OpenAICompatBatchClient",
            _FakeBatchClientConcurrent,
        ):
            (fast_status, fast_events), (batch_status, batch_events) = await asyncio.gather(
                _call_fast(),
                _call_batch(),
            )

        self.assertEqual(fast_status, 200)
        self.assertEqual(batch_status, 200)
        self.assertTrue(fast_events)
        self.assertTrue(batch_events)

        fast_run_ids = {str(e.get("run_id") or "") for e in fast_events if e.get("run_id")}
        batch_run_ids = {str(e.get("run_id") or "") for e in batch_events if e.get("run_id")}
        self.assertEqual(len(fast_run_ids), 1)
        self.assertEqual(len(batch_run_ids), 1)
        self.assertTrue(fast_run_ids.isdisjoint(batch_run_ids))

        fast_text = [e for e in fast_events if e.get("type") == "text"]
        batch_text = [e for e in batch_events if e.get("type") == "text"]
        self.assertTrue(any("FAST_CONCURRENT_OK" in str(e.get("text") or "") for e in fast_text))
        self.assertTrue(any("BATCH_CONCURRENT_OK" in str(e.get("text") or "") for e in batch_text))

        fast_route = [e for e in fast_events if e.get("type") == "route"]
        batch_route = [e for e in batch_events if e.get("type") == "route"]
        self.assertEqual(len(fast_route), 1)
        self.assertEqual(len(batch_route), 1)
        self.assertEqual(str(fast_route[0].get("mode") or ""), "fast")
        self.assertEqual(str(batch_route[0].get("mode") or ""), "batch")

        fast_done = [e for e in fast_events if e.get("type") == "done"]
        batch_done = [e for e in batch_events if e.get("type") == "done"]
        self.assertEqual(len(fast_done), 1)
        self.assertEqual(len(batch_done), 1)
        for done in (fast_done[0], batch_done[0]):
            self.assertIn("usage", done)
            self.assertIn("run_usage", done)
            self.assertIn("session_usage", done)


if __name__ == "__main__":
    unittest.main()
