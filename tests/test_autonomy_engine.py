import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone

from thomas.autonomy.engine import AutonomyEngine
from thomas.autonomy.policy import AutonomyPolicy
from thomas.autonomy.scheduler import EngineTiming
from thomas.autonomy.store import AutonomyStore


class TestAutonomyEngine(unittest.IsolatedAsyncioTestCase):
    ENV_KEYS = ("THOMAS_AUTONOMY_NO_HUMAN_MODE", "THOMAS_NO_HUMAN_MODE", "THOMAS_GUARDRAILS_NO_HUMAN_MODE")

    async def asyncSetUp(self):
        self._previous_env = {k: os.environ.get(k) for k in self.ENV_KEYS}
        for k in self.ENV_KEYS:
            os.environ.pop(k, None)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "autonomy.sqlite3")
        self.store = AutonomyStore(self.db_path)
        self.policy = AutonomyPolicy()  # default policy
        self.engine = AutonomyEngine(
            store=self.store,
            policy=self.policy,
            timing=EngineTiming(scheduler_tick_s=0.05, claim_batch=4, lock_ttl_s=5.0),
            max_concurrency=1,
        )
        await self.engine.start()

    async def asyncTearDown(self):
        await self.engine.stop()
        self.store.close()
        self.tmpdir.cleanup()
        for k in self.ENV_KEYS:
            previous = self._previous_env.get(k)
            if previous is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = previous

    async def test_runs_low_risk_reminder(self):
        job = self.store.create_job(
            name="r",
            kind="reminder",
            payload={"text": "test reminder"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )
        self.engine.wakeup()
        # Wait for processing
        for _ in range(50):
            j2 = self.store.get_job(job.id)
            if j2.status in ("succeeded", "failed", "dead"):
                break
            await asyncio.sleep(0.05)
        j2 = self.store.get_job(job.id)
        self.assertEqual(j2.status, "succeeded")
        msgs = self.store.list_messages(limit=10)
        self.assertTrue(any("test reminder" in (m["text"] or "") for m in msgs))

    async def test_medium_risk_requires_approval(self):
        self.policy.policy["api"]["no_human_mode"] = "human"
        job = self.store.create_job(
            name="r2",
            kind="reminder",
            payload={"text": "needs approval"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="medium",
            requires_approval=True,
        )
        self.engine.wakeup()
        for _ in range(50):
            j2 = self.store.get_job(job.id)
            if j2.status == "awaiting_approval":
                break
            await asyncio.sleep(0.05)
        j2 = self.store.get_job(job.id)
        self.assertEqual(j2.status, "awaiting_approval")
        aps = self.store.list_approvals(status="pending", limit=10)
        self.assertTrue(any(a.job_id == job.id for a in aps))

    async def test_medium_risk_auto_approved_when_no_human_mode_allow(self):
        self.policy.policy["api"]["no_human_mode"] = "allow"
        job = self.store.create_job(
            name="r3",
            kind="reminder",
            payload={"text": "needs auto approval"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="medium",
            requires_approval=True,
        )
        self.engine.wakeup()
        for _ in range(60):
            j2 = self.store.get_job(job.id)
            if j2.status in ("succeeded", "failed", "dead", "cancelled"):
                break
            await asyncio.sleep(0.05)
        j2 = self.store.get_job(job.id)
        self.assertEqual(j2.status, "succeeded")
        self.assertIs(j2.requires_approval, False)
        self.assertIs(j2.approved, True)
        self.assertEqual(
            0,
            len([a for a in self.store.list_approvals(status="pending", limit=20) if a.job_id == job.id]),
        )

    async def test_medium_risk_blocked_when_no_human_mode_deny(self):
        self.policy.policy["api"]["no_human_mode"] = "deny"
        job = self.store.create_job(
            name="r4",
            kind="reminder",
            payload={"text": "needs deny"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="medium",
            requires_approval=True,
        )
        self.engine.wakeup()
        for _ in range(60):
            j2 = self.store.get_job(job.id)
            if j2.status in ("dead", "succeeded", "failed", "cancelled"):
                break
            await asyncio.sleep(0.05)
        j2 = self.store.get_job(job.id)
        self.assertEqual(j2.status, "dead")
        self.assertIs(j2.approved, None)
        self.assertIs(j2.requires_approval, True)
        self.assertEqual(
            0,
            len([a for a in self.store.list_approvals(status="pending", limit=20) if a.job_id == job.id]),
        )


if __name__ == "__main__":
    unittest.main()
