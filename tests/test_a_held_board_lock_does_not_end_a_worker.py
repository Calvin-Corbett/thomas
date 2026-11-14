"""A board lock that times out is a reported failure in the worker's finalize path, not a crash.

record_evidence and the idle dispatch now hold the board lock and raise TimeoutError after 10 seconds.
The worker's three board wrappers used to let that propagate out of the loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import scripts.crew.workboard.worker_dispatch as wd


def _timeout(*_a, **_k):
    raise TimeoutError("timed out waiting for lock: board.lock")


def test_set_task_status_reports_a_lock_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wd.workboard_task_manager, "set_task_status", _timeout)
    ok, message = wd._set_task_status_safe(workboard_path=tmp_path / "b.md", task_id="t", status="done", actor="a")
    assert ok is False and "timed out" in message


def test_send_message_reports_a_lock_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wd.workboard_message, "send_message", _timeout)
    ok, message = wd._send_message_safe(
        workboard_path=tmp_path / "b.md", sender="a", recipient="b", task_id="t", summary="s",
        kind="status", priority="p1", requested_action="none", decision="approved",
    )  # fmt: skip
    assert ok is False and "timed out" in message


def test_release_claim_reports_a_lock_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wd.workboard_claim, "release", _timeout)
    ok, message = wd._release_claim_safe(
        workboard_path=tmp_path / "b.md", agent="a", allow_dirty_release=False, dirty_release_reason=""
    )
    assert ok is False and "timed out" in message


def test_other_errors_still_propagate(monkeypatch, tmp_path: Path) -> None:
    def boom(*_a, **_k):
        raise KeyError("a real bug")

    monkeypatch.setattr(wd.workboard_task_manager, "set_task_status", boom)
    with pytest.raises(KeyError):
        wd._set_task_status_safe(workboard_path=tmp_path / "b.md", task_id="t", status="done", actor="a")
