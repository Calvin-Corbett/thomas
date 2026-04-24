from tests.test_server_mission_control_remote_access_base import (
    MissionControlRemoteAccessCase,
    parse_ndjson,
)


class TestServerMissionControlRemoteAccessAuth(MissionControlRemoteAccessCase):
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
        events = parse_ndjson(await with_auth.text())
        self.assertTrue(events)
        self.assertEqual(str(events[0].get("type") or ""), "snapshot")

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
