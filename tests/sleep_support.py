"""A test that skips its code's waits, without taking the sleep out of every other thread.

``module.time`` is the one global ``time`` module, so patching its ``sleep`` also reached the background loops an
earlier test had left running in the same process. They then ran flat out and starved the test: one that takes 12 s
had not finished after 900.
"""

from __future__ import annotations

import threading
import time

import pytest


def skip_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    """``time.sleep`` returns at once on the thread running this test, and nowhere else."""
    real, mine = time.sleep, threading.get_ident()
    monkeypatch.setattr(time, "sleep", lambda seconds: None if threading.get_ident() == mine else real(seconds))
