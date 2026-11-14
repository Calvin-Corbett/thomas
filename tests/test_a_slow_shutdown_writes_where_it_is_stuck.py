"""A shutdown that takes long says where it is, instead of sitting silent.

On 2026-11-09 the caged server wrote its exit record at 17:18:06 and its process ended at 17:20:59. Nothing was logged
in those 173 seconds, the port was closed, and the next server could not start until the old one was gone, so the app
was unreachable for five and a half minutes. Nothing could say which step was waiting.
"""

import time

from thomas.core import event_loop_lag


def _wait_for(folder, count, limit_s=5.0):
    ends = time.monotonic() + limit_s
    while time.monotonic() < ends:
        found = sorted(folder.glob("shutdown-*.txt"))
        if len(found) >= count:
            return found
        time.sleep(0.02)
    return sorted(folder.glob("shutdown-*.txt"))


def test_a_shutdown_still_going_writes_every_threads_stack_and_keeps_writing(tmp_path):
    done = event_loop_lag.watch_shutdown(0.05, folder=tmp_path, limit=3)
    try:
        found = _wait_for(tmp_path, 2)
    finally:
        done.set()
    assert len(found) >= 2
    text = found[0].read_text(encoding="utf-8")
    assert "shutting down" in text
    assert "Main thread" in text
    assert "test_a_shutdown_still_going_writes_every_threads_stack_and_keeps_writing" in text


def test_a_shutdown_that_ends_in_time_writes_nothing(tmp_path):
    done = event_loop_lag.watch_shutdown(0.3, folder=tmp_path, limit=3)
    done.set()
    time.sleep(0.5)
    assert list(tmp_path.glob("shutdown-*.txt")) == []


def test_the_watch_stops_after_its_limit(tmp_path):
    done = event_loop_lag.watch_shutdown(0.03, folder=tmp_path, limit=2)
    try:
        _wait_for(tmp_path, 2)
        time.sleep(0.2)
    finally:
        done.set()
    assert len(list(tmp_path.glob("shutdown-*.txt"))) == 2
