import json
import tempfile
import unittest
from unittest.mock import patch

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

    async def test_mission_control_returns_live_contract_with_session_background_activity(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        chat_resp = await self.client.post(
            "/api/v2/chat",
            json={
                "session_id": sid,
                "profile": "local",
                "mode": "fast",
                "message": "please turn on tool details",
            },
        )
        self.assertEqual(chat_resp.status, 200)
        _ = await chat_resp.text()

        rows = [
            {
                "execution_id": "exec-chat-live",
                "task_id": "chat-turn-on-tool-details",
                "session_id": sid,
                "summary": "please turn on tool details",
                "progress_summary": "Task queued for task-bot execution.",
                "state": "queued",
                "created_at": "2026-04-07T15:00:00+00:00",
                "updated_at": "2026-04-07T15:00:10+00:00",
                "backend_type": "task_manager",
                "claimed_owner": "",
                "proof_status": "missing",
                "parent_execution_id": "",
                "actor": "task-manager-agent",
                "transitions": [],
            }
        ]
        with patch("thomas.server.routes.mission_control_routes.task_bot_runtime.list_executions", return_value=rows):
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
        run_agents = [
            a
            for a in agents
            if str(a.get("session_id") or "") == sid
            and str(a.get("source") or "") in {"chat_run", "task_bot_execution"}
        ]
        self.assertGreaterEqual(len(run_agents), 1)
        first = run_agents[0]
        self.assertIn(str(first.get("room") or ""), room_ids)
        self.assertEqual(str(first.get("session_id") or ""), sid)
        self.assertTrue(str(first.get("created_at") or "").strip())
        if str(first.get("source") or "") == "chat_run":
            self.assertTrue(str(first.get("run_id") or "").strip())
            self.assertTrue(str(first.get("started_at") or "").strip())
        else:
            self.assertTrue(str(first.get("execution_id") or "").strip())

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

    async def test_mission_jobs_returns_task_bot_payload_when_autonomy_unavailable(self):
        resp = await self.client.get("/api/mission/jobs?limit=180")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)
        jobs = payload.get("jobs") or []
        self.assertIsInstance(jobs, list)
        self.assertEqual(int(payload.get("count") or 0), len(jobs))
        if jobs:
            self.assertTrue(all(str(row.get("source") or "") == "task_bot_execution" for row in jobs))
        self.assertIn("filters", payload)
        self.assertEqual(int((payload.get("filters") or {}).get("limit", 0)), 180)

    async def test_mission_jobs_include_task_bot_executions(self):
        rows = [
            {
                "execution_id": "exec-chat-123",
                "task_id": "chat-fix-123",
                "session_id": "sess-chat-123",
                "summary": "Fix the demo project controls",
                "progress_summary": "Task running: Fix the demo project controls",
                "state": "executing",
                "created_at": "2026-04-07T15:00:00+00:00",
                "updated_at": "2026-04-07T15:01:00+00:00",
                "backend_type": "task_manager",
                "claimed_owner": "task-manager-agent",
                "proof_status": "missing",
                "parent_execution_id": "",
                "actor": "task-manager-agent",
            }
        ]
        with patch("thomas.server.routes.mission_tasks.task_bot_runtime.list_executions", return_value=rows):
            resp = await self.client.get("/api/mission/jobs?limit=20")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)
        jobs = payload.get("jobs") or []
        self.assertEqual(len(jobs), 1)
        first = jobs[0]
        self.assertEqual(str(first.get("source") or ""), "task_bot_execution")
        self.assertEqual(str(first.get("execution_id") or ""), "exec-chat-123")
        self.assertEqual(str(first.get("task_id") or ""), "chat-fix-123")
        self.assertEqual(str(first.get("status") or ""), "executing")
        self.assertEqual(str(first.get("summary") or ""), "Fix the demo project controls")
        self.assertNotIn("unavailable", payload)

    async def test_mission_jobs_filter_task_bot_by_conversation_id_alias(self):
        rows = [
            {
                "execution_id": "exec-chat-456",
                "task_id": "chat-fix-456",
                "conversation_id": "sess-chat-456",
                "summary": "Fix follow-up bug",
                "progress_summary": "Task queued for task-bot execution.",
                "state": "queued",
                "created_at": "2026-04-07T15:10:00+00:00",
                "updated_at": "2026-04-07T15:10:10+00:00",
                "backend_type": "task_manager",
            }
        ]
        with patch("thomas.server.routes.mission_tasks.task_bot_runtime.list_executions", return_value=rows):
            resp = await self.client.get("/api/mission/jobs?session_id=sess-chat-456&limit=20")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        jobs = payload.get("jobs") or []
        self.assertEqual(len(jobs), 1)
        self.assertEqual(str(jobs[0].get("session_id") or ""), "sess-chat-456")

    async def test_mission_control_includes_task_bot_agents(self):
        rows = [
            {
                "execution_id": "exec-chat-123",
                "task_id": "chat-fix-123",
                "session_id": "sess-chat-123",
                "summary": "Fix the demo project controls",
                "progress_summary": "Task running: Fix the demo project controls",
                "state": "executing",
                "created_at": "2026-04-07T15:00:00+00:00",
                "updated_at": "2026-04-07T15:01:00+00:00",
                "backend_type": "task_manager",
                "claimed_owner": "task-manager-agent",
                "proof_status": "missing",
                "parent_execution_id": "",
                "actor": "task-manager-agent",
                "transitions": [
                    {
                        "state": "executing",
                "summary": "Task running: Fix the demo project controls",
                        "occurred_at": "2026-04-07T15:01:00+00:00",
                    }
                ],
            }
        ]
        with patch("thomas.server.routes.mission_control_routes.task_bot_runtime.list_executions", return_value=rows):
            resp = await self.client.get("/api/mission/control")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIs(payload.get("ok"), True)
        agents = payload.get("agents") or []
        task_agents = [row for row in agents if str(row.get("source") or "") == "task_bot_execution"]
        self.assertEqual(len(task_agents), 1)
        self.assertEqual(str(task_agents[0].get("execution_id") or ""), "exec-chat-123")
        self.assertEqual(str(task_agents[0].get("summary") or ""), "Fix the demo project controls")

    async def test_mission_control_task_bot_agent_uses_conversation_id_alias(self):
        rows = [
            {
                "execution_id": "exec-chat-789",
                "task_id": "chat-fix-789",
                "conversation_id": "sess-chat-789",
                "summary": "Queued chat task",
                "progress_summary": "Task queued for task-bot execution.",
                "state": "queued",
                "created_at": "2026-04-07T15:20:00+00:00",
                "updated_at": "2026-04-07T15:20:10+00:00",
                "backend_type": "task_manager",
                "transitions": [],
            }
        ]
        with patch("thomas.server.routes.mission_control_routes.task_bot_runtime.list_executions", return_value=rows):
            resp = await self.client.get("/api/mission/control")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        agents = payload.get("agents") or []
        task_agents = [row for row in agents if str(row.get("execution_id") or "") == "exec-chat-789"]
        self.assertEqual(len(task_agents), 1)
        self.assertEqual(str(task_agents[0].get("session_id") or ""), "sess-chat-789")

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

    async def test_chat_prompt_routes_to_background_task_manager(self):
        session_resp = await self.client.post("/api/session/new")
        self.assertEqual(session_resp.status, 200)
        session_id = str((await session_resp.json()).get("session_id") or "")
        self.assertTrue(session_id)

        prompt = "Monitor this repo 24/7 and keep working continuously to triage and fix urgent issues."
        chat_resp = await self.client.post(
            "/api/v2/chat",
            json={
                "session_id": session_id,
                "profile": "local",
                "mode": "fast",
                "message": prompt,
            },
        )
        self.assertEqual(chat_resp.status, 200)
        _ = await chat_resp.text()

        rows = [
            {
                "execution_id": "exec-chat-background",
                "task_id": "chat-monitor-repo",
                "session_id": session_id,
                "summary": prompt,
                "progress_summary": "Task queued for task-bot execution.",
                "state": "queued",
                "created_at": "2026-04-07T15:10:00+00:00",
                "updated_at": "2026-04-07T15:10:10+00:00",
                "backend_type": "task_manager",
                "claimed_owner": "",
                "proof_status": "missing",
                "parent_execution_id": "",
                "actor": "task-manager-agent",
            }
        ]
        with patch("thomas.server.routes.mission_tasks.task_bot_runtime.list_executions", return_value=rows):
            jobs_resp = await self.client.get(f"/api/mission/jobs?session_id={session_id}&limit=80")
        self.assertEqual(jobs_resp.status, 200)
        jobs_payload = await jobs_resp.json()
        self.assertIs(jobs_payload.get("ok"), True)
        rows = jobs_payload.get("jobs") or []
        self.assertGreaterEqual(len(rows), 1)
        task_rows = [row for row in rows if str(row.get("source") or "") == "task_bot_execution"]
        self.assertGreaterEqual(len(task_rows), 1)
        self.assertTrue(any(str(row.get("session_id") or "") == session_id for row in task_rows))

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
        self.assertIs(jobs_payload.get("ok"), True)
        self.assertIsInstance(jobs_payload.get("jobs") or [], list)

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

if __name__ == "__main__":
    unittest.main()
