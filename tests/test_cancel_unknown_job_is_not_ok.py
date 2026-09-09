"""Cancelling a job that does not exist is an error, not a success.

2026-09-05, live on :8899: POST /api/mission/jobs/nope-123/cancel answered
{"ok": true}. The route maps KeyError to 404, but the store's cancel_job
updated zero rows in silence and even wrote a "job.cancelled" audit entry for
a job that never existed. A stop button must not say "stopped" about nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.marketplace.autonomy.store import AutonomyStore


def test_cancel_unknown_job_raises_and_writes_no_audit(tmp_path: Path) -> None:
    store = AutonomyStore(str(tmp_path / "autonomy.sqlite"))

    with pytest.raises(KeyError):
        store.cancel_job("nope-123", actor="mission_control")

    audits = (
        [row for row in store.list_audit(limit=50) if row.get("job_id") == "nope-123"]
        if hasattr(store, "list_audit")
        else []
    )
    assert audits == []


def test_cancel_known_job_still_cancels(tmp_path: Path) -> None:
    store = AutonomyStore(str(tmp_path / "autonomy.sqlite"))
    job = store.create_job(name="n", kind="chat", payload={}, schedule=None, next_run_at=None)

    store.cancel_job(job.id, actor="mission_control")

    assert store.get_job(job.id).status == "cancelled"


def test_set_job_status_on_unknown_job_raises(tmp_path: Path) -> None:
    store = AutonomyStore(str(tmp_path / "autonomy.sqlite"))

    with pytest.raises(KeyError):
        store.set_job_status("nope-123", "queued")
