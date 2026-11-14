"""The mission job, approval and remote-token routes of the Jobs and Work row, split out of test_server_mission_control.py."""

import json
import tempfile
import unittest
from pathlib import Path

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


class TestServerMissionControlApprovalAudit(AioHTTPTestCase):
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
