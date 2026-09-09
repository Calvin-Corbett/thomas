import json
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

    def test_catch_up_uses_unique_missed_occurrences(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "s.json"
            fired = []
            clock = FakeClock(datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc))
            scheduler = TaskScheduler(
                lambda goal, channel: fired.append((goal, channel)),
                schedule_path=path,
                now_fn=clock.now,
                catch_up_limit=2,
                max_workers=1,
                auto_start=False,
            )
            try:
                scheduler.add_task("m", "* * * * *", "ping", "default")
                clock.advance(timedelta(minutes=5))
                scheduler._poll_once()

                import time as _t

                deadline = _t.monotonic() + 2.0
                history = []
                while _t.monotonic() < deadline:
                    history = scheduler.list_tasks()[0]["run_history"]
                    if len(history) == 2:
                        break
                    _t.sleep(0.01)

                scheduled = [row["scheduled_for"] for row in history]
                self.assertEqual(len(fired), 2)
                self.assertEqual(len(scheduled), 2)
                self.assertEqual(len(set(scheduled)), 2)
                self.assertTrue(scheduled[0].startswith("2026-02-18T12:01:00"))
                self.assertTrue(scheduled[1].startswith("2026-02-18T12:02:00"))
                self.assertTrue(scheduler.list_tasks()[0]["next_run"].startswith("2026-02-18T12:06:00"))
            finally:
                scheduler.stop()

    def test_skipped_misfire_advancement_is_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "s.json"
            clock = FakeClock(datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc))
            scheduler = TaskScheduler(
                lambda _goal, _channel: None,
                schedule_path=path,
                now_fn=clock.now,
                auto_start=False,
            )
            try:
                scheduler.add_task("m", "* * * * *", "ping", "default")
                scheduler.update_task("m", misfire_policy="skip", misfire_grace_s=5)
                clock.advance(timedelta(minutes=5))
                scheduler._poll_once()

                persisted = json.loads(path.read_text(encoding="utf-8"))
                persisted_next = persisted["tasks"][0]["next_run_at"]
                self.assertTrue(persisted_next.startswith("2026-02-18T12:06:00"))
                self.assertEqual(scheduler.list_tasks()[0]["run_history"], [])
            finally:
                scheduler.stop()


if __name__ == "__main__":
    unittest.main()
