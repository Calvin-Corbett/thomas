import json
import tempfile
import unittest

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


class TestServerMissionControl(AioHTTPTestCase):
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

    async def test_mission_control_returns_live_contract_with_run_agents(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        chat_resp = await self.client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "profile": "local",
                "mode": "fast",
                "text": "please turn on tool details",
            },
        )
        self.assertEqual(chat_resp.status, 200)
        _ = await chat_resp.text()

        resp = await self.client.get("/api/mission/control")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()

        self.assertIs(payload.get("ok"), True)
        self.assertIn("rooms", payload)
        self.assertIn("agents", payload)
        self.assertIn("events", payload)
        self.assertIn("totals", payload)

        room_ids = {str(r.get("id") or "") for r in (payload.get("rooms") or [])}
        self.assertTrue({"inbox", "planning", "tools", "files", "review", "done"}.issubset(room_ids))

        agents = payload.get("agents") or []
        run_agents = [a for a in agents if str(a.get("source") or "") == "chat_run"]
        self.assertGreaterEqual(len(run_agents), 1)
        first = run_agents[0]
        self.assertIn(str(first.get("room") or ""), room_ids)
        self.assertTrue(str(first.get("run_id") or "").strip())

    async def test_mission_control_includes_topology_and_approvals(self):
        resp = await self.client.get("/api/mission/control")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()

        self.assertIn("topology", payload)
        topology = payload.get("topology") or {}
        self.assertIn("nodes", topology)
        self.assertIn("edges", topology)
        self.assertIn("timeline", topology)

        self.assertIn("approvals", payload)
        approvals = payload.get("approvals") or {}
        self.assertIn("autonomy", approvals)
        self.assertIn("guardrails", approvals)
        self.assertIn("pending_total", approvals)

    async def test_mission_control_job_actions_404_when_autonomy_unavailable(self):
        resp = await self.client.post("/api/mission/jobs/job-123/cancel", json={})
        self.assertEqual(resp.status, 404)

    async def test_mission_approval_actions_404_when_unavailable(self):
        autonomy = await self.client.post(
            "/api/mission/approvals/autonomy/approval-123/decision",
            json={"approve": True},
        )
        self.assertEqual(autonomy.status, 404)

        guardrails = await self.client.post(
            "/api/mission/approvals/guardrails/resolve",
            json={"run_id": "run-1", "tool_call_id": "call-1", "approve": True},
        )
        self.assertEqual(guardrails.status, 404)

    async def test_mission_alert_notify_noop_when_channels_missing(self):
        resp = await self.client.post(
            "/api/mission/alerts/notify",
            json={"alerts": [{"severity": "high", "title": "test", "detail": "detail"}]},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)
        channels = payload.get("channels") or {}
        self.assertIn("desktop", channels)
        self.assertIn("noop", channels)

    async def test_mission_page_serves_html(self):
        resp = await self.client.get("/mission")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("Mission Control", text)
        self.assertIn("Open Office", text)
        self.assertIn("Show Idle", text)
        self.assertIn("Agent Activity", text)

    async def test_mission_stream_returns_snapshot_payload(self):
        resp = await self.client.get("/api/mission/stream?max_updates=1&interval=0.01")
        self.assertEqual(resp.status, 200)
        self.assertIn("application/x-ndjson", str(resp.headers.get("Content-Type") or ""))
        events = _parse_ndjson(await resp.text())
        self.assertGreaterEqual(len(events), 1)
        first = events[0]
        self.assertEqual(str(first.get("type") or ""), "snapshot")
        payload = first.get("payload") or {}
        self.assertIs(payload.get("ok"), True)
        self.assertIn("agents", payload)
        self.assertIn("events", payload)

    async def test_mission_stream_rejects_invalid_interval(self):
        resp = await self.client.get("/api/mission/stream?max_updates=1&interval=oops")
        self.assertEqual(resp.status, 400)

    async def test_mission_benchmark_routes_return_payloads(self):
        packs_resp = await self.client.get("/api/mission/benchmarks/packs")
        self.assertEqual(packs_resp.status, 200)
        packs_payload = await packs_resp.json()
        self.assertIs(packs_payload.get("ok"), True)
        self.assertIn("packs", packs_payload)
        self.assertIn("default_pack", packs_payload)
        packs = packs_payload.get("packs") or []
        self.assertGreaterEqual(len(packs), 1)
        self.assertTrue(str((packs[0] or {}).get("key") or "").strip())

        runs_resp = await self.client.get("/api/mission/benchmarks/runs?limit=5")
        self.assertEqual(runs_resp.status, 200)
        runs_payload = await runs_resp.json()
        self.assertIs(runs_payload.get("ok"), True)
        self.assertIn("runs", runs_payload)
        self.assertIn("runs_dir", runs_payload)

        jobs_resp = await self.client.get("/api/mission/benchmarks/jobs")
        self.assertEqual(jobs_resp.status, 200)
        jobs_payload = await jobs_resp.json()
        self.assertIs(jobs_payload.get("ok"), True)
        self.assertIn("jobs", jobs_payload)


class TestServerMissionControlRemoteAccess(AioHTTPTestCase):
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
            server=ServerConfig(access_mode="remote", api_token="test-token"),
        )
        return create_app(cfg)

    async def test_mission_control_requires_remote_token(self):
        no_auth = await self.client.get("/api/mission/control")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/mission/control",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)
        payload = await with_auth.json()
        self.assertIs(payload.get("ok"), True)

    async def test_mission_stream_requires_remote_token(self):
        no_auth = await self.client.get("/api/mission/stream?max_updates=1")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/mission/stream?max_updates=1&interval=0.01",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)
        events = _parse_ndjson(await with_auth.text())
        self.assertTrue(events)
        self.assertEqual(str(events[0].get("type") or ""), "snapshot")

    async def test_mission_benchmark_routes_require_remote_token(self):
        no_auth_packs = await self.client.get("/api/mission/benchmarks/packs")
        self.assertEqual(no_auth_packs.status, 401)

        no_auth = await self.client.get("/api/mission/benchmarks/runs")
        self.assertEqual(no_auth.status, 401)

        with_auth_packs = await self.client.get(
            "/api/mission/benchmarks/packs",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth_packs.status, 200)
        packs_payload = await with_auth_packs.json()
        self.assertIs(packs_payload.get("ok"), True)

        with_auth = await self.client.get(
            "/api/mission/benchmarks/runs",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)
        payload = await with_auth.json()
        self.assertIs(payload.get("ok"), True)

    async def test_mission_alert_notify_requires_remote_token(self):
        no_auth = await self.client.post("/api/mission/alerts/notify", json={})
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.post(
            "/api/mission/alerts/notify",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )
        self.assertEqual(with_auth.status, 200)
        payload = await with_auth.json()
        self.assertIs(payload.get("ok"), True)


if __name__ == "__main__":
    unittest.main()
