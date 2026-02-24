import json
import os
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


class _FakeSwarmOrchestrator:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def astream(self, *, user_request, subagents):  # noqa: ANN001
        _ = user_request
        _ = subagents
        yield {"type": "swarm_start", "agent": "orchestrator"}
        yield {
            "type": "swarm_done",
            "ok": True,
            "final": "SWARM_TELEMETRY_OK",
            "summary": {"status": {"a": "done"}},
            "duration_ms": 5,
        }


class _FakeSwarmOrchestratorPolicyProbe:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        self._tool_call = kwargs.get("tool_call")

    async def astream(self, *, user_request, subagents):  # noqa: ANN001
        _ = user_request
        _ = subagents
        probe = {"ok": False, "error": "no tool callback"}
        if callable(self._tool_call):
            probe = await self._tool_call("shell.exec", {"command": "echo hi", "cwd": "."})
        yield {"type": "policy_probe", "tool_result": probe}
        yield {
            "type": "swarm_done",
            "ok": True,
            "final": "SWARM_POLICY_PROBE_OK",
            "summary": {"status": {"a": "done"}},
            "duration_ms": 5,
        }


class _FakeSwarmOrchestratorWithUsage:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def astream(self, *, user_request, subagents):  # noqa: ANN001
        _ = user_request
        _ = subagents
        yield {
            "type": "swarm_done",
            "ok": True,
            "final": "SWARM_BUDGET_OK",
            "summary": {"status": {"a": "done"}},
            "duration_ms": 5,
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }


class TestServerSwarmModeTelemetry(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        self._db_path = f"{self._tmpdir.name}\\prefs_swarm_runtime.sqlite"
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
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_swarm_done_includes_usage_fields(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.swarm_mode.SwarmOrchestrator", _FakeSwarmOrchestrator):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "run swarm now",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        swarm_done = [e for e in events if e.get("type") == "swarm_done"]
        self.assertEqual(len(swarm_done), 1)
        done = swarm_done[0]
        self.assertEqual(done.get("final"), "SWARM_TELEMETRY_OK")
        self.assertEqual(done.get("usage"), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        self.assertEqual(done.get("run_usage"), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        self.assertEqual(done.get("session_usage"), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    async def test_swarm_mode_respects_tool_policy_wrapper(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        patch_resp = await self.client.patch(
            "/api/preferences",
            json={"advanced": {"tools": {"allow_shell": True, "require_command_approval": True}}},
        )
        self.assertEqual(patch_resp.status, 200)

        with patch("thomas.server.swarm_mode.SwarmOrchestrator", _FakeSwarmOrchestratorPolicyProbe):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "run swarm now",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        probes = [e for e in events if e.get("type") == "policy_probe"]
        self.assertEqual(len(probes), 1)
        tool_result = probes[0].get("tool_result") or {}
        self.assertFalse(bool(tool_result.get("ok", True)))
        self.assertIn("require_command_approval", str(tool_result.get("error") or ""))

    async def test_swarm_done_includes_budget_report_when_advanced_cost_enabled(self):
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

        with patch("thomas.server.swarm_mode.SwarmOrchestrator", _FakeSwarmOrchestratorWithUsage):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "run swarm now",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        swarm_done = [e for e in events if e.get("type") == "swarm_done"]
        self.assertEqual(len(swarm_done), 1)
        token_report = swarm_done[0].get("token_report") or {}
        budget = token_report.get("budget") or {}
        self.assertEqual((budget.get("session") or {}).get("used_tokens"), 3)
        self.assertEqual((budget.get("session") or {}).get("budget_tokens"), 1000)


if __name__ == "__main__":
    unittest.main()
