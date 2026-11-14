"""A test that skips its code's waits leaves every other thread its sleep.

Two full runs on 2026-10-30 lost a worker to the timeout at the same test. It had replaced ``checks.time.sleep``, which
is the global ``time.sleep``, so the background loops earlier tests had left in that process stopped waiting and ran
flat out. The test takes 12 s; with eight such loops it had not finished after 330 s.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest

from tests.sleep_support import skip_sleeps

TESTS = Path(__file__).resolve().parent
PATCHES_THE_GLOBAL_SLEEP = re.compile(r"""setattr\([^,\n]*\btime\b[^,\n]*,\s*["']sleep["']""")


def test_only_the_tests_own_thread_skips_its_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    skip_sleeps(monkeypatch)
    took: list[float] = []

    def other_thread() -> None:
        began = time.monotonic()
        time.sleep(0.05)
        took.append(time.monotonic() - began)

    began = time.monotonic()
    time.sleep(60)
    assert time.monotonic() - began < 30, "this thread's wait was skipped"

    thread = threading.Thread(target=other_thread)
    thread.start()
    thread.join()
    assert took[0] >= 0.04, "another thread still waits"


def test_no_test_takes_the_sleep_out_of_every_thread() -> None:
    found = [
        str(path.relative_to(TESTS))
        for path in TESTS.rglob("*.py")
        if path.name != "sleep_support.py" and PATCHES_THE_GLOBAL_SLEEP.search(path.read_text(encoding="utf-8"))
    ]

    assert not found, "use tests.sleep_support.skip_sleeps"
