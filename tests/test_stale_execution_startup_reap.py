"""A task killed by a restart is dead the moment the server comes back."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from thomas.server import stale_execution_sweep as sweep


def _rows(monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    by_id = {r["execution_id"]: r for r in records}
    monkeypatch.setattr(sweep.task_bot_runtime, "list_executions", lambda *a, **k: list(records))
    monkeypatch.setattr(sweep.task_bot_runtime, "get_execution", lambda eid, *a, **k: by_id.get(eid))
    monkeypatch.setattr(
        sweep.task_bot_runtime,
        "fail_execution",
        lambda eid, **kw: failed.append({"execution_id": eid, **kw}),
    )
    monkeypatch.setattr(sweep, "record_issue", lambda **kw: None)
    return failed


def _rec(eid: str, stamped: datetime, state: str = "executing") -> dict[str, Any]:
    return {"execution_id": eid, "state": state, "last_heartbeat_at": stamped.isoformat(), "summary": eid}


def test_a_task_from_the_previous_process_is_closed_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before this, a restart left the task showing as running for 15 quiet
    minutes plus up to another 10 until the next sweep -- and a restart is
    exactly when someone is sitting there watching."""
    boot = datetime.now(timezone.utc)
    failed = _rows(monkeypatch, [_rec("exec-old", boot - timedelta(seconds=20))])

    closed = sweep.sweep_stale_executions(None, orphaned_before=boot)

    assert closed == 1
    assert failed[0]["execution_id"] == "exec-old"
    assert failed[0]["blocker"] == "stale_interrupted"
    assert "interrupted by a restart" in failed[0]["summary"]


def test_a_task_this_process_started_is_never_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole safety argument: a live worker stamps a time after boot."""
    boot = datetime.now(timezone.utc)
    failed = _rows(monkeypatch, [_rec("exec-live", boot + timedelta(seconds=5))])

    assert sweep.sweep_stale_executions(None, orphaned_before=boot) == 0
    assert failed == []


def test_a_finished_task_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    boot = datetime.now(timezone.utc)
    failed = _rows(monkeypatch, [_rec("exec-done", boot - timedelta(hours=1), state="completed")])

    assert sweep.sweep_stale_executions(None, orphaned_before=boot) == 0
    assert failed == []


def test_the_idle_sweep_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without orphaned_before the old behaviour must be exactly preserved:
    quiet longer than the threshold closes, quieter than it does not."""
    now = datetime.now(timezone.utc)
    failed = _rows(
        monkeypatch,
        [
            _rec("exec-quiet", now - timedelta(minutes=30)),
            _rec("exec-recent", now - timedelta(minutes=1)),
        ],
    )

    closed = sweep.sweep_stale_executions(None)

    assert closed == 1
    assert failed[0]["execution_id"] == "exec-quiet"
    assert "no activity for" in failed[0]["summary"]


def test_a_record_with_no_timestamp_is_not_reaped_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown age must not be treated as old -- under-reaping is the safe
    direction, since the idle sweep will still catch it."""
    boot = datetime.now(timezone.utc)
    failed = _rows(monkeypatch, [{"execution_id": "exec-blank", "state": "executing", "summary": ""}])

    assert sweep.sweep_stale_executions(None, orphaned_before=boot) == 0
    assert failed == []
