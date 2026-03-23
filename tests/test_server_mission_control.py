import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.app_keys import APP_APPROVALS_BROKER


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
        self.assertEqual(str(first.get("session_id") or ""), sid)
        self.assertTrue(str(first.get("created_at") or "").strip())
        self.assertTrue(str(first.get("started_at") or "").strip())

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

    async def test_mission_objective_flow_reflects_in_control_and_stream(self):
        bootstrap = await self.client.post("/api/mission/autopilot/bootstrap", json={})
        self.assertEqual(bootstrap.status, 200)
        bootstrap_payload = await bootstrap.json()
        self.assertIs(bootstrap_payload.get("ok"), True)

        create_resp = await self.client.post(
            "/api/mission/autopilot/objectives",
            json={
                "goal": "Continuously triage urgent incidents and keep mission dashboard current",
                "cadence": "continuous",
                "every_seconds": 120,
                "workflow": "orchestrator_worker",
                "worker_count": 2,
            },
        )
        self.assertEqual(create_resp.status, 200)
        create_payload = await create_resp.json()
        self.assertIs(create_payload.get("ok"), True)
        objective_id = str(create_payload.get("objective_id") or "")
        self.assertTrue(objective_id)
        created_job = create_payload.get("job") or {}
        job_id = str(created_job.get("id") or "")
        self.assertTrue(job_id)

        control_resp = await self.client.get("/api/mission/control")
        self.assertEqual(control_resp.status, 200)
        control_payload = await control_resp.json()
        self.assertIs(control_payload.get("ok"), True)
        control_agents = control_payload.get("agents") or []
        control_job_ids = {
            str(row.get("job_id") or "") for row in control_agents if str(row.get("source") or "") == "autonomy_job"
        }
        self.assertIn(job_id, control_job_ids)

        stream_resp = await self.client.get("/api/mission/stream?max_updates=1&interval=0.01")
        self.assertEqual(stream_resp.status, 200)
        stream_events = _parse_ndjson(await stream_resp.text())
        self.assertGreaterEqual(len(stream_events), 1)
        stream_payload = (stream_events[0] or {}).get("payload") or {}
        stream_agents = stream_payload.get("agents") or []
        stream_job_ids = {
            str(row.get("job_id") or "") for row in stream_agents if str(row.get("source") or "") == "autonomy_job"
        }
        self.assertIn(job_id, stream_job_ids)

        stop_resp = await self.client.post(f"/api/mission/autopilot/objectives/{objective_id}/stop", json={})
        self.assertEqual(stop_resp.status, 200)
        stop_payload = await stop_resp.json()
        self.assertIs(stop_payload.get("ok"), True)
        self.assertGreaterEqual(int(stop_payload.get("matched_jobs") or 0), 1)

        active_resp = await self.client.get(
            f"/api/mission/autopilot/objectives?objective_id={objective_id}&active_only=1&limit=10"
        )
        self.assertEqual(active_resp.status, 200)
        active_payload = await active_resp.json()
        self.assertIs(active_payload.get("ok"), True)
        self.assertEqual(active_payload.get("objectives"), [])

        all_resp = await self.client.get(
            f"/api/mission/autopilot/objectives?objective_id={objective_id}&active_only=0&limit=10"
        )
        self.assertEqual(all_resp.status, 200)
        all_payload = await all_resp.json()
        self.assertIs(all_payload.get("ok"), True)
        all_rows = all_payload.get("objectives") or []
        self.assertGreaterEqual(len(all_rows), 1)
        terminal_statuses = {
            str(row.get("status") or "").strip().lower()
            for row in all_rows
            if str(row.get("objective_id") or "") == objective_id
        }
        self.assertTrue(terminal_statuses)
        self.assertTrue(terminal_statuses.issubset({"cancelled", "canceled", "failed", "succeeded", "dead"}))

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

    async def test_mission_job_create_rejects_non_object_json_without_bootstrap(self):
        resp = await self.client.post("/api/mission/jobs", json=["bad"])
        self.assertEqual(resp.status, 400)

        jobs_resp = await self.client.get("/api/mission/jobs?limit=10")
        self.assertEqual(jobs_resp.status, 200)
        jobs_payload = await jobs_resp.json()
        self.assertIs(jobs_payload.get("unavailable"), True)

    async def test_mission_job_create_parses_requires_approval_string_false(self):
        resp = await self.client.post(
            "/api/mission/jobs",
            json={"kind": "workflow_task", "goal": "Ship v1", "requires_approval": "false"},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        job = payload.get("job") or {}
        self.assertFalse(bool(job.get("requires_approval")))

    async def test_mission_autopilot_objective_rejects_non_object_json_without_bootstrap(self):
        resp = await self.client.post("/api/mission/autopilot/objectives", json=["bad"])
        self.assertEqual(resp.status, 400)

        list_resp = await self.client.get("/api/mission/autopilot/objectives?active_only=0&limit=10")
        self.assertEqual(list_resp.status, 200)
        list_payload = await list_resp.json()
        self.assertIs(list_payload.get("unavailable"), True)

    async def test_mission_autopilot_objective_parses_requires_approval_string_false(self):
        resp = await self.client.post(
            "/api/mission/autopilot/objectives",
            json={"goal": "Keep triage moving", "requires_approval": "false"},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        job = payload.get("job") or {}
        self.assertFalse(bool(job.get("requires_approval")))

    async def test_mission_guardrails_approval_resolve_succeeds_with_broker(self):
        class _Broker:
            def __init__(self) -> None:
                self.calls = []

            async def resolve(
                self,
                *,
                run_id: str,
                tool_call_id: str,
                approved: bool,
                allow_session_tool: bool,
                tool_name: str | None,
                session_id: str | None,
            ) -> bool:
                self.calls.append(
                    {
                        "run_id": run_id,
                        "tool_call_id": tool_call_id,
                        "approved": approved,
                        "allow_session_tool": allow_session_tool,
                        "tool_name": tool_name,
                        "session_id": session_id,
                    }
                )
                return True

        broker = _Broker()
        app_state = getattr(self.app, "_state", None)
        if isinstance(app_state, dict):
            app_state[APP_APPROVALS_BROKER] = broker
        else:
            self.app[APP_APPROVALS_BROKER] = broker

        resp = await self.client.post(
            "/api/mission/approvals/guardrails/resolve",
            json={
                "run_id": "run-42",
                "tool_call_id": "call-7",
                "approve": True,
                "allow_session_tool": True,
                "tool_name": "shell.exec",
                "session_id": "sess-9",
            },
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)
        self.assertEqual(str(payload.get("run_id") or ""), "run-42")
        self.assertEqual(str(payload.get("tool_call_id") or ""), "call-7")
        self.assertEqual(str(payload.get("decision") or ""), "approve")
        self.assertIs(payload.get("allow_session_tool"), True)

        self.assertEqual(len(broker.calls), 1)
        self.assertEqual(
            broker.calls[0],
            {
                "run_id": "run-42",
                "tool_call_id": "call-7",
                "approved": True,
                "allow_session_tool": True,
                "tool_name": "shell.exec",
                "session_id": "sess-9",
            },
        )

    async def test_mission_guardrails_approval_resolve_rejects_non_object_json(self):
        class _Broker:
            def __init__(self) -> None:
                self.calls = []

            async def resolve(self, **kwargs):
                self.calls.append(kwargs)
                return True

        broker = _Broker()
        app_state = getattr(self.app, "_state", None)
        if isinstance(app_state, dict):
            app_state[APP_APPROVALS_BROKER] = broker
        else:
            self.app[APP_APPROVALS_BROKER] = broker

        resp = await self.client.post("/api/mission/approvals/guardrails/resolve", json=["bad"])
        self.assertEqual(resp.status, 400)
        self.assertEqual(broker.calls, [])

    async def test_mission_guardrails_approval_resolve_parses_string_false_for_allow_session_tool(self):
        class _Broker:
            def __init__(self) -> None:
                self.calls = []

            async def resolve(self, **kwargs):
                self.calls.append(kwargs)
                return True

        broker = _Broker()
        app_state = getattr(self.app, "_state", None)
        if isinstance(app_state, dict):
            app_state[APP_APPROVALS_BROKER] = broker
        else:
            self.app[APP_APPROVALS_BROKER] = broker

        resp = await self.client.post(
            "/api/mission/approvals/guardrails/resolve",
            json={
                "run_id": "run-7",
                "tool_call_id": "call-3",
                "approve": True,
                "allow_session_tool": "false",
            },
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("allow_session_tool"), False)
        self.assertEqual(len(broker.calls), 1)
        self.assertIs(broker.calls[0]["allow_session_tool"], False)

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
        self.assertIn("<title>Thomas Mission Control</title>", text)
        self.assertIn("Mission Control", text)
        self.assertIn('id="missions-list"', text)
        self.assertIn('id="approvals-list"', text)
        self.assertIn('id="agents-grid"', text)

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

    async def test_mission_autopilot_objective_routes_require_token_and_support_lifecycle(self):
        no_auth_create = await self.client.post(
            "/api/mission/autopilot/objectives",
            json={"goal": "Keep mission queue healthy", "cadence": "continuous", "every_seconds": 90},
        )
        self.assertEqual(no_auth_create.status, 401)

        with_auth_create = await self.client.post(
            "/api/mission/autopilot/objectives",
            headers={"Authorization": "Bearer test-token"},
            json={"goal": "Keep mission queue healthy", "cadence": "continuous", "every_seconds": 90},
        )
        self.assertEqual(with_auth_create.status, 200)
        create_payload = await with_auth_create.json()
        self.assertIs(create_payload.get("ok"), True)
        objective_id = str(create_payload.get("objective_id") or "")
        self.assertTrue(objective_id)

        no_auth_list = await self.client.get("/api/mission/autopilot/objectives?active_only=0&limit=20")
        self.assertEqual(no_auth_list.status, 401)

        with_auth_list = await self.client.get(
            f"/api/mission/autopilot/objectives?objective_id={objective_id}&active_only=0&limit=20",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth_list.status, 200)
        list_payload = await with_auth_list.json()
        self.assertIs(list_payload.get("ok"), True)
        objective_ids = {str(row.get("objective_id") or "") for row in (list_payload.get("objectives") or [])}
        self.assertIn(objective_id, objective_ids)

        no_auth_stop = await self.client.post(f"/api/mission/autopilot/objectives/{objective_id}/stop", json={})
        self.assertEqual(no_auth_stop.status, 401)

        with_auth_stop = await self.client.post(
            f"/api/mission/autopilot/objectives/{objective_id}/stop",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )
        self.assertEqual(with_auth_stop.status, 200)
        stop_payload = await with_auth_stop.json()
        self.assertIs(stop_payload.get("ok"), True)
        self.assertGreaterEqual(int(stop_payload.get("matched_jobs") or 0), 1)

        with_auth_active = await self.client.get(
            f"/api/mission/autopilot/objectives?objective_id={objective_id}&active_only=1&limit=20",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth_active.status, 200)
        active_payload = await with_auth_active.json()
        self.assertIs(active_payload.get("ok"), True)
        self.assertEqual(active_payload.get("objectives"), [])

    async def test_mission_job_routes_require_token_and_support_mutations(self):
        no_auth_create = await self.client.post(
            "/api/mission/jobs",
            json={
                "kind": "workflow_task",
                "name": "Remote Job Auth",
                "goal": "Summarize top incidents",
                "schedule": {"type": "interval", "every_seconds": 120},
            },
        )
        self.assertEqual(no_auth_create.status, 401)

        with_auth_create = await self.client.post(
            "/api/mission/jobs",
            headers={"Authorization": "Bearer test-token"},
            json={
                "kind": "workflow_task",
                "name": "Remote Job Auth",
                "goal": "Summarize top incidents",
                "schedule": {"type": "interval", "every_seconds": 120},
            },
        )
        self.assertEqual(with_auth_create.status, 200)
        create_payload = await with_auth_create.json()
        self.assertIs(create_payload.get("ok"), True)
        job = create_payload.get("job") or {}
        job_id = str(job.get("id") or "")
        self.assertTrue(job_id)

        no_auth_list = await self.client.get("/api/mission/jobs?limit=20")
        self.assertEqual(no_auth_list.status, 401)

        with_auth_list = await self.client.get(
            "/api/mission/jobs?limit=20",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth_list.status, 200)
        list_payload = await with_auth_list.json()
        self.assertIs(list_payload.get("ok"), True)
        listed_ids = {str(row.get("id") or "") for row in (list_payload.get("jobs") or [])}
        self.assertIn(job_id, listed_ids)

        no_auth_run_now = await self.client.post(f"/api/mission/jobs/{job_id}/run_now", json={})
        self.assertEqual(no_auth_run_now.status, 401)

        with_auth_run_now = await self.client.post(
            f"/api/mission/jobs/{job_id}/run_now",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )
        self.assertEqual(with_auth_run_now.status, 200)
        run_now_payload = await with_auth_run_now.json()
        self.assertIs(run_now_payload.get("ok"), True)
        self.assertEqual(str(run_now_payload.get("action") or ""), "run_now")

        no_auth_requeue = await self.client.post(f"/api/mission/jobs/{job_id}/requeue", json={})
        self.assertEqual(no_auth_requeue.status, 401)

        with_auth_requeue = await self.client.post(
            f"/api/mission/jobs/{job_id}/requeue",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )
        self.assertEqual(with_auth_requeue.status, 200)
        requeue_payload = await with_auth_requeue.json()
        self.assertIs(requeue_payload.get("ok"), True)
        self.assertEqual(str(requeue_payload.get("action") or ""), "requeue")

        no_auth_cancel = await self.client.post(f"/api/mission/jobs/{job_id}/cancel", json={})
        self.assertEqual(no_auth_cancel.status, 401)

        with_auth_cancel = await self.client.post(
            f"/api/mission/jobs/{job_id}/cancel",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )
        self.assertEqual(with_auth_cancel.status, 200)
        cancel_payload = await with_auth_cancel.json()
        self.assertIs(cancel_payload.get("ok"), True)
        self.assertEqual(str(cancel_payload.get("action") or ""), "cancel")

    async def test_mission_approval_routes_require_token_and_surface_missing_resources(self):
        no_auth_autonomy = await self.client.post(
            "/api/mission/approvals/autonomy/approval-123/decision",
            json={"approve": True},
        )
        self.assertEqual(no_auth_autonomy.status, 401)

        with_auth_autonomy = await self.client.post(
            "/api/mission/approvals/autonomy/approval-123/decision",
            headers={"Authorization": "Bearer test-token"},
            json={"approve": True},
        )
        self.assertEqual(with_auth_autonomy.status, 404)
        self.assertIn("autonomy store is not available", await with_auth_autonomy.text())

        no_auth_guardrails = await self.client.post(
            "/api/mission/approvals/guardrails/resolve",
            json={"run_id": "run-1", "tool_call_id": "call-1", "approve": True},
        )
        self.assertEqual(no_auth_guardrails.status, 401)

        with_auth_guardrails = await self.client.post(
            "/api/mission/approvals/guardrails/resolve",
            headers={"Authorization": "Bearer test-token"},
            json={"run_id": "run-1", "tool_call_id": "call-1", "approve": True},
        )
        self.assertEqual(with_auth_guardrails.status, 404)
        self.assertIn("pending approval not found", await with_auth_guardrails.text())

    async def test_mission_autonomy_approval_decision_succeeds_with_seeded_store(self):
        from thomas.marketplace.autonomy.store import AutonomyStore

        store = AutonomyStore(str((Path(self._tmpdir.name) / "autonomy-remote.sqlite3").resolve()))
        self.addCleanup(store.close)
        app_state = getattr(self.app, "_state", None)
        if isinstance(app_state, dict):
            app_state["autonomy_store"] = store
        else:
            self.app["autonomy_store"] = store

        job = store.create_job(
            name="Seeded Approval Job",
            kind="workflow_task",
            payload={"goal": "Verify approval decision path"},
            schedule=None,
            next_run_at=None,
            risk_class="high",
            requires_approval=True,
        )
        approval = store.create_approval(
            job_id=job.id,
            action={"kind": "tool.execute", "tool_name": "shell.exec"},
            risk_class="high",
        )

        resp = await self.client.post(
            f"/api/mission/approvals/autonomy/{approval.id}/decision",
            headers={"Authorization": "Bearer test-token"},
            json={"approve": True, "actor": "e2e-test", "reason": "safe and expected"},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)
        self.assertEqual(str(payload.get("approval_id") or ""), approval.id)
        self.assertEqual(str(payload.get("job_id") or ""), job.id)
        self.assertEqual(str(payload.get("status") or ""), "approved")

        updated_approval = store.get_approval(approval.id)
        self.assertEqual(updated_approval.status, "approved")
        self.assertEqual(updated_approval.decided_by, "e2e-test")
        self.assertEqual(updated_approval.decision_reason, "safe and expected")

        updated_job = store.get_job(job.id)
        self.assertIs(updated_job.approved, True)
        self.assertIs(updated_job.requires_approval, False)

    async def test_mission_autonomy_approval_decision_denied_cancels_job(self):
        from thomas.marketplace.autonomy.store import AutonomyStore

        store = AutonomyStore(str((Path(self._tmpdir.name) / "autonomy-remote-deny.sqlite3").resolve()))
        self.addCleanup(store.close)
        app_state = getattr(self.app, "_state", None)
        if isinstance(app_state, dict):
            app_state["autonomy_store"] = store
        else:
            self.app["autonomy_store"] = store

        job = store.create_job(
            name="Seeded Deny Approval Job",
            kind="workflow_task",
            payload={"goal": "Verify deny path"},
            schedule=None,
            next_run_at=None,
            risk_class="critical",
            requires_approval=True,
        )
        approval = store.create_approval(
            job_id=job.id,
            action={"kind": "tool.execute", "tool_name": "shell.exec"},
            risk_class="critical",
        )

        resp = await self.client.post(
            f"/api/mission/approvals/autonomy/{approval.id}/decision",
            headers={"Authorization": "Bearer test-token"},
            json={"approve": False, "actor": "e2e-deny", "reason": "unsafe operation"},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)
        self.assertEqual(str(payload.get("approval_id") or ""), approval.id)
        self.assertEqual(str(payload.get("job_id") or ""), job.id)
        self.assertEqual(str(payload.get("status") or ""), "denied")

        updated_approval = store.get_approval(approval.id)
        self.assertEqual(updated_approval.status, "denied")
        self.assertEqual(updated_approval.decided_by, "e2e-deny")
        self.assertEqual(updated_approval.decision_reason, "unsafe operation")

        updated_job = store.get_job(job.id)
        self.assertEqual(updated_job.status, "cancelled")
        self.assertIs(updated_job.cancelled, True)

    async def test_mission_autonomy_approval_decision_is_idempotent_after_terminal_state(self):
        from thomas.marketplace.autonomy.store import AutonomyStore

        store = AutonomyStore(str((Path(self._tmpdir.name) / "autonomy-remote-idempotent.sqlite3").resolve()))
        self.addCleanup(store.close)
        app_state = getattr(self.app, "_state", None)
        if isinstance(app_state, dict):
            app_state["autonomy_store"] = store
        else:
            self.app["autonomy_store"] = store

        job = store.create_job(
            name="Seeded Idempotent Approval Job",
            kind="workflow_task",
            payload={"goal": "Verify idempotent decision"},
            schedule=None,
            next_run_at=None,
            risk_class="high",
            requires_approval=True,
        )
        approval = store.create_approval(
            job_id=job.id,
            action={"kind": "tool.execute", "tool_name": "shell.exec"},
            risk_class="high",
        )

        first = await self.client.post(
            f"/api/mission/approvals/autonomy/{approval.id}/decision",
            headers={"Authorization": "Bearer test-token"},
            json={"approve": True, "actor": "first-actor", "reason": "approved once"},
        )
        self.assertEqual(first.status, 200)
        first_payload = await first.json()
        self.assertIs(first_payload.get("ok"), True)
        self.assertEqual(str(first_payload.get("status") or ""), "approved")

        second = await self.client.post(
            f"/api/mission/approvals/autonomy/{approval.id}/decision",
            headers={"Authorization": "Bearer test-token"},
            json={"approve": False, "actor": "second-actor", "reason": "try to reverse"},
        )
        self.assertEqual(second.status, 200)
        second_payload = await second.json()
        self.assertIs(second_payload.get("ok"), True)
        self.assertEqual(str(second_payload.get("status") or ""), "approved")

        updated_approval = store.get_approval(approval.id)
        self.assertEqual(updated_approval.status, "approved")
        self.assertEqual(updated_approval.decided_by, "first-actor")
        self.assertEqual(updated_approval.decision_reason, "approved once")

    async def test_mission_autonomy_approval_decision_emits_expected_audit_events(self):
        from thomas.marketplace.autonomy.store import AutonomyStore

        store = AutonomyStore(str((Path(self._tmpdir.name) / "autonomy-remote-audit.sqlite3").resolve()))
        self.addCleanup(store.close)
        app_state = getattr(self.app, "_state", None)
        if isinstance(app_state, dict):
            app_state["autonomy_store"] = store
        else:
            self.app["autonomy_store"] = store

        job = store.create_job(
            name="Seeded Audit Approval Job",
            kind="workflow_task",
            payload={"goal": "Verify approval audit events"},
            schedule=None,
            next_run_at=None,
            risk_class="high",
            requires_approval=True,
        )
        approval = store.create_approval(
            job_id=job.id,
            action={"kind": "tool.execute", "tool_name": "shell.exec"},
            risk_class="high",
        )

        resp = await self.client.post(
            f"/api/mission/approvals/autonomy/{approval.id}/decision",
            headers={"Authorization": "Bearer test-token"},
            json={"approve": True, "actor": "audit-actor", "reason": "audit coverage"},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)

        audit_rows = store.list_audit(job_id=job.id, limit=20)
        event_types = [str(row.event_type or "") for row in audit_rows]
        self.assertIn("approval.requested", event_types)
        self.assertIn("approval.decided", event_types)

        decided = next(row for row in audit_rows if str(row.event_type or "") == "approval.decided")
        self.assertEqual(str(decided.actor or ""), "audit-actor")
        decided_detail = decided.detail if isinstance(decided.detail, dict) else {}
        self.assertEqual(str(decided_detail.get("approval_id") or ""), approval.id)
        self.assertEqual(str(decided_detail.get("status") or ""), "approved")
        self.assertEqual(str(decided_detail.get("reason") or ""), "audit coverage")

    async def test_mission_autonomy_approval_repeat_decision_does_not_duplicate_decided_audit(self):
        from thomas.marketplace.autonomy.store import AutonomyStore

        store = AutonomyStore(str((Path(self._tmpdir.name) / "autonomy-remote-audit-idempotent.sqlite3").resolve()))
        self.addCleanup(store.close)
        app_state = getattr(self.app, "_state", None)
        if isinstance(app_state, dict):
            app_state["autonomy_store"] = store
        else:
            self.app["autonomy_store"] = store

        job = store.create_job(
            name="Seeded Audit Idempotent Job",
            kind="workflow_task",
            payload={"goal": "Verify approval decided audit idempotency"},
            schedule=None,
            next_run_at=None,
            risk_class="high",
            requires_approval=True,
        )
        approval = store.create_approval(
            job_id=job.id,
            action={"kind": "tool.execute", "tool_name": "shell.exec"},
            risk_class="high",
        )

        first = await self.client.post(
            f"/api/mission/approvals/autonomy/{approval.id}/decision",
            headers={"Authorization": "Bearer test-token"},
            json={"approve": True, "actor": "audit-first", "reason": "first decision"},
        )
        self.assertEqual(first.status, 200)
        first_payload = await first.json()
        self.assertEqual(str(first_payload.get("status") or ""), "approved")

        second = await self.client.post(
            f"/api/mission/approvals/autonomy/{approval.id}/decision",
            headers={"Authorization": "Bearer test-token"},
            json={"approve": False, "actor": "audit-second", "reason": "second decision"},
        )
        self.assertEqual(second.status, 200)
        second_payload = await second.json()
        self.assertEqual(str(second_payload.get("status") or ""), "approved")

        audit_rows = store.list_audit(job_id=job.id, limit=30)
        decided_rows = [row for row in audit_rows if str(row.event_type or "") == "approval.decided"]
        self.assertEqual(len(decided_rows), 1)
        decided = decided_rows[0]
        self.assertEqual(str(decided.actor or ""), "audit-first")
        decided_detail = decided.detail if isinstance(decided.detail, dict) else {}
        self.assertEqual(str(decided_detail.get("approval_id") or ""), approval.id)
        self.assertEqual(str(decided_detail.get("status") or ""), "approved")
        self.assertEqual(str(decided_detail.get("reason") or ""), "first decision")

    async def test_mission_autonomy_approval_audit_timestamps_are_chronological(self):
        from thomas.marketplace.autonomy.store import AutonomyStore

        store = AutonomyStore(str((Path(self._tmpdir.name) / "autonomy-remote-audit-chronology.sqlite3").resolve()))
        self.addCleanup(store.close)
        app_state = getattr(self.app, "_state", None)
        if isinstance(app_state, dict):
            app_state["autonomy_store"] = store
        else:
            self.app["autonomy_store"] = store

        job = store.create_job(
            name="Seeded Audit Chronology Job",
            kind="workflow_task",
            payload={"goal": "Verify approval audit chronology"},
            schedule=None,
            next_run_at=None,
            risk_class="high",
            requires_approval=True,
        )
        approval = store.create_approval(
            job_id=job.id,
            action={"kind": "tool.execute", "tool_name": "shell.exec"},
            risk_class="high",
        )

        resp = await self.client.post(
            f"/api/mission/approvals/autonomy/{approval.id}/decision",
            headers={"Authorization": "Bearer test-token"},
            json={"approve": True, "actor": "chrono-actor", "reason": "chronology check"},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)

        audit_rows = store.list_audit(job_id=job.id, limit=30)

        def _event_for(event_type: str):
            for row in audit_rows:
                if str(row.event_type or "") != event_type:
                    continue
                detail = row.detail if isinstance(row.detail, dict) else {}
                if str(detail.get("approval_id") or "") == approval.id:
                    return row
            return None

        requested = _event_for("approval.requested")
        decided = _event_for("approval.decided")
        self.assertIsNotNone(requested)
        self.assertIsNotNone(decided)
        assert requested is not None
        assert decided is not None
        self.assertLessEqual(requested.ts, decided.ts)


if __name__ == "__main__":
    unittest.main()
