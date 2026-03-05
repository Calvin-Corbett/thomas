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


class _FakeAgentLoopContract:
    def __init__(self, run_cfg, llm, tools, **kwargs):  # noqa: ANN001
        _ = run_cfg
        _ = llm
        _ = tools
        _ = kwargs

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _ = prompt
        _ = kwargs
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "swarm", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": str(tools_policy),
                "autonomy_level": 3,
                "autonomy_name": "Auto",
            },
        )
        yield AgentEvent.agent_done(
            text="SWARM_CONTRACT_OK",
            iterations=1,
            tool_calls=0,
            token_report={
                "rules_of_road": {
                    "signals": {"writes_detected": True},
                }
            },
        )


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
            models={
                "local": ModelConfig(
                    name="local",
                    provider="openai_compat",
                    base_url="http://127.0.0.1:11434/v1",
                    model="dummy",
                )
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        with patch(
            "thomas.server.routes.chat_v2.register_chat_v2_routes",
            side_effect=RuntimeError("legacy-chat-required"),
        ):
            return create_app(cfg)

    async def test_swarm_stream_events_have_run_id_and_usage_contract(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopContract):
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

        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        done = done_events[0]
        self.assertEqual(done.get("text"), "SWARM_CONTRACT_OK")
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
