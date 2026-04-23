import os
import tempfile
import unittest
from datetime import datetime, timezone

from thomas.marketplace.autonomy.scheduler import compute_next_run
from thomas.marketplace.autonomy.store import AutonomyStore


class TestAutonomyStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "autonomy.sqlite3")
        self.store = AutonomyStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.tmpdir.cleanup()

    def test_migration_creates_tables(self):
        # If migrate() didn't run, basic insert would fail
        job = self.store.create_job(
            name="t",
            kind="reminder",
            payload={"text": "hi"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )
        self.assertEqual(job.kind, "reminder")

    def test_approvals_flow(self):
        job = self.store.create_job(
            name="med",
            kind="reminder",
            payload={"text": "x"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="medium",
        )
        ap = self.store.create_approval(job_id=job.id, action={"kind": "reminder"}, risk_class="medium")
        self.assertEqual(ap.status, "pending")
        ap2 = self.store.decide_approval(approval_id=ap.id, approve=True, actor="test", reason="ok")
        self.assertEqual(ap2.status, "approved")

    def test_compute_next_run_interval(self):
        now = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        sched = {"type": "interval", "every_seconds": 3600}
        nxt = compute_next_run(sched, now)
        self.assertTrue(nxt > now)


if __name__ == "__main__":
    unittest.main()
