import json
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.app_keys import APP_APPROVALS_BROKER
from thomas.server.routes.mission_support import _latest_run_event


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class TestLatestRunEventCache(unittest.TestCase):
    def test_terminal_runs_are_cached_while_active_runs_stay_live(self):
        class FakeRunStore:
            def __init__(self):
                self.calls = 0

            def stream_replay(self, run_id):
                self.calls += 1
                yield {"run_id": run_id, "seq": self.calls}

        store = FakeRunStore()
        first = _latest_run_event(store, "finished-run", terminal=True)
        second = _latest_run_event(store, "finished-run", terminal=True)
        self.assertEqual(first, second)
        self.assertEqual(store.calls, 1)

        _latest_run_event(store, "active-run", terminal=False)
        _latest_run_event(store, "active-run", terminal=False)
        self.assertEqual(store.calls, 3)


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

        # NOTE: must NOT match a UI control intent (see
        # thomas/models/chat_controls.py:_BOOLEAN_SETTING_SPECS). UI control
        # chats short-circuit before _start_run_writer fires, so the run
        # store never gets a chat_run row and this assertion fails. The
        # phrasing below is innocuous and falls through to the regular
        # agent loop.
        chat_resp = await self.client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "profile": "local",
                "mode": "fast",
                "text": "Summarize the weather forecast for tomorrow.",
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

    async def test_chat_prompt_does_not_auto_start_autopilot_objective(self):
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
        rows = list_payload.get("objectives") or []
        goals = [str(row.get("goal") or "").lower() for row in rows]
        self.assertFalse(any("24/7" in goal or "continuously" in goal for goal in goals))

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

    async def test_the_old_mission_page_address_leads_to_the_agents_page(self):
        plain = await self.client.get("/mission", allow_redirects=False)
        self.assertEqual(plain.status, 302)
        self.assertEqual(plain.headers["Location"], "/agents")
        embedded = await self.client.get("/mission?embed=1", allow_redirects=False)
        self.assertEqual(embedded.status, 302)
        self.assertEqual(embedded.headers["Location"], "/agents?embed=1")

    async def test_mission_control_snapshot_cache_coalesces_and_fresh_bypasses(self):
        with patch(
            "thomas.server.routes.mission_control_routes._utc_iso_now",
            side_effect=("first-build", "forced-build"),
        ):
            first_resp = await self.client.get("/api/mission/control")
            second_resp = await self.client.get("/api/mission/control")
            fresh_resp = await self.client.get("/api/mission/control?fresh=1")

        self.assertEqual(first_resp.status, 200)
        self.assertEqual(second_resp.status, 200)
        self.assertEqual(fresh_resp.status, 200)
        first = await first_resp.json()
        second = await second_resp.json()
        fresh = await fresh_resp.json()
        self.assertEqual(first.get("generated_at"), "first-build")
        self.assertEqual(second.get("generated_at"), "first-build")
        self.assertEqual(fresh.get("generated_at"), "forced-build")

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
