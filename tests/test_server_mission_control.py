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

    async def test_mission_jobs_returns_empty_payload_when_autonomy_unavailable(self):
        resp = await self.client.get("/api/mission/jobs?limit=180")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)
        self.assertEqual(payload.get("jobs"), [])
        self.assertEqual(payload.get("count"), 0)
        self.assertIs(payload.get("unavailable"), True)
        self.assertIn("filters", payload)
        self.assertEqual(int((payload.get("filters") or {}).get("limit", 0)), 180)

    async def test_mission_job_create_auto_bootstraps_autonomy_runtime(self):
        create_resp = await self.client.post(
            "/api/mission/jobs",
            json={
                "kind": "workflow_task",
                "name": "Auto Bootstrap Job",
                "goal": "Summarize project health",
                "schedule": {"type": "interval", "every_seconds": 600},
            },
        )
        self.assertEqual(create_resp.status, 200)
        create_payload = await create_resp.json()
        self.assertIs(create_payload.get("ok"), True)
        job = create_payload.get("job") or {}
        self.assertEqual(str(job.get("kind") or ""), "workflow_task")
        self.assertTrue(str(job.get("id") or "").strip())

        jobs_resp = await self.client.get("/api/mission/jobs?limit=10")
        self.assertEqual(jobs_resp.status, 200)
        jobs_payload = await jobs_resp.json()
        self.assertIs(jobs_payload.get("ok"), True)
        self.assertNotIn("unavailable", jobs_payload)
        self.assertGreaterEqual(int(jobs_payload.get("count") or 0), 1)

    async def test_mission_autopilot_objective_lifecycle(self):
        bootstrap = await self.client.post("/api/mission/autopilot/bootstrap", json={})
        self.assertEqual(bootstrap.status, 200)
        bootstrap_payload = await bootstrap.json()
        self.assertIs(bootstrap_payload.get("ok"), True)
        self.assertIs(bootstrap_payload.get("enabled"), True)
        self.assertIs(bool((bootstrap_payload.get("engine") or {}).get("running")), True)

        create_resp = await self.client.post(
            "/api/mission/autopilot/objectives",
            json={
                "goal": "Keep backlog triaged and summarize urgent risks",
                "cadence": "continuous",
                "every_seconds": 180,
                "start_immediately": False,
                "workflow": "orchestrator_worker",
                "worker_count": 3,
            },
        )
        self.assertEqual(create_resp.status, 200)
        create_payload = await create_resp.json()
        self.assertIs(create_payload.get("ok"), True)
        objective_id = str(create_payload.get("objective_id") or "")
        self.assertTrue(objective_id)
        job = create_payload.get("job") or {}
        self.assertEqual(str(job.get("kind") or ""), "workflow_task")
        schedule = job.get("schedule") or {}
        self.assertEqual(str(schedule.get("type") or ""), "interval")

        list_resp = await self.client.get("/api/mission/autopilot/objectives?active_only=0&limit=50")
        self.assertEqual(list_resp.status, 200)
        list_payload = await list_resp.json()
        self.assertIs(list_payload.get("ok"), True)
        rows = list_payload.get("objectives") or []
        ids = {str(row.get("objective_id") or "") for row in rows}
        self.assertIn(objective_id, ids)

        stop_resp = await self.client.post(f"/api/mission/autopilot/objectives/{objective_id}/stop", json={})
        self.assertEqual(stop_resp.status, 200)
        stop_payload = await stop_resp.json()
        self.assertIs(stop_payload.get("ok"), True)
        self.assertGreaterEqual(int(stop_payload.get("matched_jobs") or 0), 1)

    async def test_chat_prompt_auto_starts_autopilot_objective(self):
        session_resp = await self.client.post("/api/session/new")
        self.assertEqual(session_resp.status, 200)
        session_id = str((await session_resp.json()).get("session_id") or "")
        self.assertTrue(session_id)

        prompt = "Monitor this repo 24/7 and keep working continuously to triage and fix urgent issues."
        chat_resp = await self.client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "profile": "local",
                "mode": "fast",
                "text": prompt,
            },
        )
        self.assertEqual(chat_resp.status, 200)
        _ = await chat_resp.text()

        list_resp = await self.client.get("/api/mission/autopilot/objectives?active_only=0&limit=80")
        self.assertEqual(list_resp.status, 200)
        list_payload = await list_resp.json()
        self.assertIs(list_payload.get("ok"), True)
        self.assertNotIn("unavailable", list_payload)
        rows = list_payload.get("objectives") or []
        self.assertGreaterEqual(len(rows), 1)
        goals = [str(row.get("goal") or "").lower() for row in rows]
        self.assertTrue(any("24/7" in goal or "continuously" in goal for goal in goals))

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

    async def test_mission_alert_notify_rejects_private_webhook_target(self):
        resp = await self.client.post(
            "/api/mission/alerts/notify",
            json={
                "alerts": [{"severity": "high", "title": "test"}],
                "channels": {"webhook_url": "http://127.0.0.1:9000/hook"},
            },
        )
        self.assertEqual(resp.status, 400)
        self.assertIn("public host", await resp.text())

    async def test_mission_alert_notify_rejects_email_header_injection(self):
        resp = await self.client.post(
            "/api/mission/alerts/notify",
            json={
                "alerts": [{"severity": "high", "title": "test"}],
                "channels": {
                    "email_to": "alerts@example.com",
                    "subject": "Mission Alert\nBcc: injected@example.com",
                },
            },
        )
        self.assertEqual(resp.status, 400)
        self.assertIn("invalid subject", await resp.text())

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
