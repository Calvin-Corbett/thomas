from pathlib import Path

from tests.test_server_mission_control_remote_access_base import MissionControlRemoteAccessCase


class TestServerMissionControlRemoteAccessAutonomy(MissionControlRemoteAccessCase):
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
