"""Stopping a run is not a failure, and it is final."""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from thomas.core import task_bot_runtime as t


@pytest.fixture()
def root() -> pathlib.Path:
    return pathlib.Path(tempfile.mkdtemp())


def _running(root: pathlib.Path) -> str:
    ex = t.create_execution(session_id="s", summary="Build a snake game", repo_root=root)
    eid = ex["execution_id"]
    for state in ("queued", "claimed", "executing"):
        t.update_execution(eid, state=state, repo_root=root)
    return eid


def test_a_stop_is_recorded_as_cancelled_not_failed(root: pathlib.Path) -> None:
    """Every Stop used to call fail_execution(blocker="cancelled"), so the run
    landed in `failed` with a failed proof. A deliberate stop was then
    indistinguishable from a crash in the task list."""
    eid = _running(root)

    t.cancel_execution(eid, actor="user", summary="Stopped by you.", repo_root=root)
    rec = t.get_execution(eid, root)

    assert rec["state"] == "cancelled"
    assert rec["state"] != "failed"
    assert rec.get("proof_status") == "cancelled"


def test_a_worker_that_finishes_anyway_cannot_relabel_the_stop(root: pathlib.Path) -> None:
    """The contradiction the owner saw: "Cancelled by user." followed seconds
    later by "Created deliverable.txt". Completion writes with force=True, which
    bypasses the transition table, so a worker reaching its own finish line
    overwrote the stop."""
    eid = _running(root)
    t.cancel_execution(eid, actor="user", repo_root=root)

    t.complete_execution(eid, actor="worker", summary="Created deliverable.txt",
                         repo_root=root, verified_success=True)

    assert t.get_execution(eid, root)["state"] == "cancelled"


def test_work_finished_before_the_stop_is_kept(root: pathlib.Path) -> None:
    """Stopping something halfway does not make the files it already wrote
    disappear."""
    eid = _running(root)

    t.cancel_execution(eid, actor="user", salvaged_artifacts=["report.pdf"], repo_root=root)
    rec = t.get_execution(eid, root)

    assert "report.pdf" in str(rec)


def test_cancelled_is_terminal(root: pathlib.Path) -> None:
    assert "cancelled" in t.TERMINAL_STATES
    assert t.ALLOWED_TRANSITIONS["cancelled"] == set()


def test_any_live_state_can_be_stopped(root: pathlib.Path) -> None:
    for live in ("requested", "queued", "claimed", "executing", "blocked", "awaiting_proof", "verified"):
        assert "cancelled" in t.ALLOWED_TRANSITIONS[live], f"{live} cannot be stopped"


def test_stopping_an_already_finished_run_changes_nothing(root: pathlib.Path) -> None:
    eid = _running(root)
    t.update_execution(eid, state="awaiting_proof", repo_root=root)
    t.attach_proof(eid, artifacts=["out.txt"], summary="done", status="verified",
                   actor="w", repo_root=root)
    t.complete_execution(eid, actor="w", summary="done", repo_root=root, verified_success=True)
    assert t.get_execution(eid, root)["state"] == "completed"

    t.request_cancel(eid, actor="user", repo_root=root)

    assert t.get_execution(eid, root)["state"] == "completed"
