import os
import tempfile
import unittest
import asyncio
from datetime import datetime, timezone

from thomas.autonomy.store import AutonomyStore
from thomas.autonomy.engine import AutonomyEngine
from thomas.autonomy.policy import AutonomyPolicy
from thomas.autonomy.scheduler import EngineTiming


class TestAutonomyEngine(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
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
        job = self.store.create_job(
            name="r2",
            kind="reminder",
            payload={"text": "needs approval"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="medium",
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


if __name__ == "__main__":
    unittest.main()
