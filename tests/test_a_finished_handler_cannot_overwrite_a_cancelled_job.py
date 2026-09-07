"""A handler that finishes late cannot turn a cancelled job back into a success (2026-09-05).

Codex measured it live in Work: Mission Control cancelled a job, the engine
never cancelled the in-flight handler, and the handler's own success write
overwrote ``cancelled`` with ``succeeded`` minutes later. The engine's
finalizers need an atomic boundary in the store: ``set_job_status(...,
preserve_cancelled=True)`` updates only a row that is not cancelled and says
whether it did, so the finalizer can skip its success audit. Explicit control
operations keep today's behaviour, and an unknown id is still a KeyError.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.marketplace.autonomy.store import AutonomyStore


def _store(tmp_path: Path) -> AutonomyStore:
    return AutonomyStore(str(tmp_path / "autonomy.sqlite"))


def test_a_late_success_does_not_overwrite_a_cancelled_job(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.create_job(name="n", kind="chat", payload={}, schedule=None, next_run_at=None)
    store.cancel_job(job.id, actor="mission_control")

    updated = store.set_job_status(job.id, "succeeded", result={"ok": True}, preserve_cancelled=True)

    assert updated is False
    assert store.get_job(job.id).status == "cancelled"


def test_a_live_job_is_finalised_normally(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.create_job(name="n", kind="chat", payload={}, schedule=None, next_run_at=None)

    updated = store.set_job_status(job.id, "succeeded", result={"ok": True}, preserve_cancelled=True)

    assert updated is True
    assert store.get_job(job.id).status == "succeeded"


def test_an_explicit_control_write_keeps_todays_behaviour(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.create_job(name="n", kind="chat", payload={}, schedule=None, next_run_at=None)
    store.cancel_job(job.id, actor="mission_control")

    updated = store.set_job_status(job.id, "queued")  # an operator re-queues on purpose

    assert updated is True
    assert store.get_job(job.id).status == "queued"


def test_an_unknown_job_is_still_a_key_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(KeyError):
        store.set_job_status("nope-123", "succeeded", preserve_cancelled=True)


def test_a_pending_cancel_is_cancelling_until_the_handler_confirms_it_stopped(tmp_path: Path) -> None:
    """Work polls the store while Pause waits for the in-flight handler; a job
    that reads "cancelled" before its handler has actually stopped lets the poll
    reconcile too early. The engine asks for a pending cancel first, awaits the
    child, and only then writes the final cancelled status."""
    store = _store(tmp_path)
    job = store.create_job(name="n", kind="chat", payload={}, schedule=None, next_run_at=None)

    store.cancel_job(job.id, actor="mission_control", pending=True)
    pending = store.get_job(job.id)
    assert pending.status == "cancelling"
    assert pending.cancelled is True

    assert store.set_job_status(job.id, "succeeded", preserve_cancelled=True) is False  # still refused while pending

    store.cancel_job(job.id, actor="engine")
    assert store.get_job(job.id).status == "cancelled"


def test_a_plain_cancel_is_unchanged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.create_job(name="n", kind="chat", payload={}, schedule=None, next_run_at=None)
    store.cancel_job(job.id, actor="mission_control")
    assert store.get_job(job.id).status == "cancelled"
