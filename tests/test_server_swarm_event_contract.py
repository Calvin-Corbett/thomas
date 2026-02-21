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


class _FakeSwarmOrchestratorNoRunId:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def astream(self, *, user_request, subagents):  # noqa: ANN001
        _ = user_request
        _ = subagents
        yield {"type": "swarm_start", "agent": "orchestrator"}
        yield {
            "type": "agent_tool_start",
            "agent": "coder",
            "task_id": "t1",
            "tool_call_id": "tc1",
            "tool": "diff.create",
            "args": {"path": "app.py", "old_str": "a", "new_str": "b"},
        }
        yield {
            "type": "agent_tool_result",
            "agent": "coder",
            "task_id": "t1",
            "tool_call_id": "tc1",
            "tool": "diff.create",
            "ok": True,
        }
        yield {
            "type": "swarm_done",
            "ok": True,
            "final": "SWARM_CONTRACT_OK",
            "summary": {"status": {"planner": "done"}},
            "duration_ms": 3,
        }


class TestServerSwarmEventContract(AioHTTPTestCase):
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

    async def test_swarm_stream_events_have_run_id_and_usage_contract(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.swarm_mode.SwarmOrchestrator", _FakeSwarmOrchestratorNoRunId):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "token_economy": "max",
                    "text": "run swarm now",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertIn("application/x-ndjson", str(resp.headers.get("Content-Type") or ""))

        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)

        run_ids = set()
        for event in events:
            self.assertIsInstance(event.get("type"), str)
            rid = str(event.get("run_id") or "").strip()
            self.assertTrue(rid)
            run_ids.add(rid)
        self.assertEqual(len(run_ids), 1)

        done_events = [e for e in events if e.get("type") == "swarm_done"]
        self.assertEqual(len(done_events), 1)
        done = done_events[0]
        self.assertEqual(done.get("final"), "SWARM_CONTRACT_OK")
        expected_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.assertEqual(done.get("usage"), expected_usage)
        self.assertEqual(done.get("run_usage"), expected_usage)
        self.assertEqual(done.get("session_usage"), expected_usage)
        self.assertIn("rules_of_road", done)
        token_report = done.get("token_report") or {}
        self.assertIn("rules_of_road", token_report)
        self.assertEqual((done.get("token_economy") or {}).get("applied"), "max")
        self.assertEqual((token_report.get("token_economy") or {}).get("applied"), "max")
        self.assertTrue(bool(done.get("rules_of_road", {}).get("signals", {}).get("writes_detected")))
        seqs = [int(e.get("seq")) for e in events]
        self.assertEqual(seqs, sorted(seqs))


if __name__ == "__main__":
    unittest.main()
