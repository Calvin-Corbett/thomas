import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from thomas.core.scheduler import TaskScheduler, _normalize_cron


class FakeClock:
    def __init__(self, start: datetime):
        self._t = start

    def now(self) -> datetime:
        return self._t

    def advance(self, delta: timedelta) -> None:
        self._t = self._t + delta


class SchedulerDelightTests(unittest.TestCase):
    def test_shorthand_and_every_minutes(self):
        self.assertEqual(_normalize_cron("@daily"), "0 0 * * *")
        self.assertEqual(_normalize_cron("every 15 minutes"), "*/15 * * * *")
        self.assertEqual(_normalize_cron("every hour"), "0 * * * *")
        self.assertEqual(_normalize_cron("every day"), "0 0 * * *")

        with self.assertRaises(ValueError):
            _normalize_cron("0 9 * *")  # 4 fields

    def test_skip_stale_misfires(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "s.json"
            fired = []
            clock = FakeClock(datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc))

            def exec_fn(goal, channel):
                fired.append((goal, channel))

            s = TaskScheduler(exec_fn, schedule_path=path, now_fn=clock.now, poll_interval_s=999, auto_start=False)
            s.add_task("m", "* * * * *", "ping", "default")

            # Switch policy to skip and set a tiny grace window
            s.update_task("m", misfire_policy="skip", misfire_grace_s=5)

            # Jump far ahead so the scheduled run is stale
            clock.advance(timedelta(minutes=2))
            s._poll_once()  # should skip stale occurrences, and not fire due to grace window
            import time as _t

            _t.sleep(0.05)

            self.assertEqual(len(fired), 0)

    def test_run_history_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "s.json"
            fired = []
            clock = FakeClock(datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc))

            def exec_fn(goal, channel):
                fired.append((goal, channel))

            s = TaskScheduler(exec_fn, schedule_path=path, now_fn=clock.now, poll_interval_s=999, auto_start=False)
            s.add_task("m", "* * * * *", "ping", "default")
            s.run_now("m")

            import time as _t

            _t.sleep(0.05)

            tasks = s.list_tasks()
            self.assertEqual(tasks[0]["id"], "m")
            self.assertTrue(len(tasks[0]["run_history"]) >= 1)


if __name__ == "__main__":
    unittest.main()
