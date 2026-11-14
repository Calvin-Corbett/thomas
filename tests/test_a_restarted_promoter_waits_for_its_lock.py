"""A restarted promoter waits for the old copy to let go, and says so when it gives up.

On 2026-09-23 the promoter task was ended and run again straight away. The new
copy found the old one still holding its single-instance lock, printed a line
nobody could see under pythonw, and exited 0, so the scheduler reported success.
The cage's egress proxy lives in the same process, so the caged Thomas lost its
network until the task was run a second time.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest
from scripts.cage import promoter_service


def test_a_lock_released_moments_later_is_taken(tmp_path: Path) -> None:
    old_copy = promoter_service._take_lock(tmp_path)
    assert old_copy is not None
    threading.Timer(0.6, old_copy.close).start()

    new_copy = promoter_service._wait_for_lock(tmp_path, wait_s=5.0, step_s=0.1)

    assert new_copy is not None
    new_copy.close()


def test_a_lock_that_stays_held_is_given_up_on(tmp_path: Path) -> None:
    old_copy = promoter_service._take_lock(tmp_path)
    try:
        assert promoter_service._wait_for_lock(tmp_path, wait_s=0.3, step_s=0.1) is None
    finally:
        old_copy.close()


def test_giving_up_is_written_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    old_copy = promoter_service._take_lock(tmp_path / "promoter")
    monkeypatch.setattr(promoter_service, "LOCK_WAIT_S", 0.3)
    try:
        with caplog.at_level(logging.WARNING, logger=promoter_service.log.name):
            assert promoter_service.main(["--cage-root", str(tmp_path), "--once"]) == 0
    finally:
        old_copy.close()

    assert "still holds the lock" in caplog.text
