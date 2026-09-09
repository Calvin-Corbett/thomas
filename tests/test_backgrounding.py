"""CAP-059 acceptance: background an inflight run and surface status, ETA, and reattach.

All tests are hermetic: the durable JSON store lives in a pytest ``tmp_path`` and
the clock is injected so ETA math is deterministic. No network, no live model.
"""

import json

import pytest

from thomas.agent.backgrounding import (
    BackgroundRunRegistry,
    BackgroundStoreError,
    ProgressSnapshot,
    ReattachHandle,
    RunState,
    RunStatus,
    estimate_eta_seconds,
)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _registry(tmp_path, clock=None):
    return BackgroundRunRegistry(tmp_path / "runs.json", clock=clock or FakeClock())


# ---------------------------------------------------------------------------
# background() records the run and it appears in list_background()
# ---------------------------------------------------------------------------


def test_background_records_and_appears_in_list(tmp_path):
    reg = _registry(tmp_path)
    snap = ProgressSnapshot(steps_done=3, phase="executing", started_at=1000.0, estimated_total=12, cursor=7)

    status = reg.background("run-1", snap)

    assert status.state is RunState.BACKGROUNDED
    assert status.progress.steps_done == 3
    assert status.progress.phase == "executing"

    listed = reg.list_background()
    assert [s.run_id for s in listed] == ["run-1"]
    assert listed[0].state is RunState.BACKGROUNDED


def test_list_background_only_backgrounded_runs_most_recent_first(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock=clock)
    reg.background("a", ProgressSnapshot(steps_done=1, started_at=clock.now))
    clock.advance(5)
    reg.background("b", ProgressSnapshot(steps_done=1, started_at=clock.now))
    clock.advance(5)
    reg.background("c", ProgressSnapshot(steps_done=1, started_at=clock.now))

    # c is foregrounded (reattached) so it drops out of the background list.
    reg.reattach("c")
    # b finishes -> terminal, also drops out.
    reg.mark_done("b")

    listed = reg.list_background()
    assert [s.run_id for s in listed] == ["a"]


# ---------------------------------------------------------------------------
# status() returns state + progress + a deterministic ETA
# ---------------------------------------------------------------------------


def test_status_returns_state_progress_and_eta_formula(tmp_path):
    clock = FakeClock(start=1000.0)
    reg = _registry(tmp_path, clock=clock)
    # started at t=1000, 2 of 10 steps done, queried at t=1010 (10s elapsed).
    reg.background("run-eta", ProgressSnapshot(steps_done=2, started_at=1000.0, estimated_total=10, cursor=2))
    clock.now = 1010.0

    status = reg.status("run-eta")

    assert isinstance(status, RunStatus)
    assert status.state is RunState.BACKGROUNDED
    assert status.progress.steps_done == 2
    # rate = 2 steps / 10s = 0.2/s; remaining = 8; eta = 8 / 0.2 = 40s.
    assert status.eta_seconds == pytest.approx(40.0)
    assert status.eta_at == pytest.approx(1050.0)


def test_eta_estimator_edge_cases():
    # No estimated_total -> unknown.
    assert estimate_eta_seconds(steps_done=5, estimated_total=None, started_at=0.0, now=10.0) is None
    # No progress yet -> unknown (no rate).
    assert estimate_eta_seconds(steps_done=0, estimated_total=10, started_at=0.0, now=10.0) is None
    # No elapsed time -> unknown.
    assert estimate_eta_seconds(steps_done=3, estimated_total=10, started_at=10.0, now=10.0) is None
    # Met/exceeded the estimate -> 0.
    assert estimate_eta_seconds(steps_done=10, estimated_total=10, started_at=0.0, now=5.0) == 0.0
    # Known-input projection: 4 of 20 in 8s -> rate 0.5/s, remaining 16 -> 32s.
    assert estimate_eta_seconds(steps_done=4, estimated_total=20, started_at=0.0, now=8.0) == pytest.approx(32.0)


def test_status_unknown_run_is_clean_not_crash(tmp_path):
    reg = _registry(tmp_path)
    status = reg.status("nope")
    assert status.state is RunState.UNKNOWN
    assert status.eta_seconds is None
    assert status.eta_at is None
    assert status.progress.steps_done == 0


# ---------------------------------------------------------------------------
# reattach() returns a handle with the correct cursor and foregrounds the run
# ---------------------------------------------------------------------------


def test_reattach_returns_handle_and_foregrounds(tmp_path):
    reg = _registry(tmp_path)
    reg.background("run-r", ProgressSnapshot(steps_done=4, phase="executing", started_at=1000.0, cursor=9))

    handle = reg.reattach("run-r")

    assert isinstance(handle, ReattachHandle)
    assert handle.ok is True
    assert handle.cursor == 9
    assert handle.progress is not None and handle.progress.steps_done == 4
    assert handle.state is RunState.RUNNING
    # Foregrounded: the run is now running, no longer backgrounded.
    assert reg.status("run-r").state is RunState.RUNNING
    assert reg.list_background() == []


def test_reattach_unknown_run_signals_cleanly(tmp_path):
    reg = _registry(tmp_path)
    handle = reg.reattach("ghost")
    assert handle.ok is False
    assert handle.state is RunState.UNKNOWN
    assert handle.reason == "unknown run"


# ---------------------------------------------------------------------------
# a finished run reports done and cannot be reattached
# ---------------------------------------------------------------------------


def test_finished_run_reports_done_and_cannot_reattach(tmp_path):
    reg = _registry(tmp_path)
    reg.background("run-f", ProgressSnapshot(steps_done=10, started_at=1000.0, estimated_total=10, cursor=10))
    reg.mark_done("run-f")

    status = reg.status("run-f")
    assert status.state is RunState.DONE
    assert status.eta_seconds == 0.0

    handle = reg.reattach("run-f")
    assert handle.ok is False
    assert handle.state is RunState.DONE
    assert "done" in handle.reason
    # State is untouched by the failed reattach.
    assert reg.status("run-f").state is RunState.DONE


def test_failed_run_reports_failed_and_cannot_reattach(tmp_path):
    reg = _registry(tmp_path)
    reg.background("run-x", ProgressSnapshot(steps_done=2, started_at=1000.0, estimated_total=10))
    reg.mark_failed("run-x")

    status = reg.status("run-x")
    assert status.state is RunState.FAILED
    assert status.eta_seconds is None

    handle = reg.reattach("run-x")
    assert handle.ok is False
    assert handle.state is RunState.FAILED


def test_cannot_background_a_terminal_run(tmp_path):
    reg = _registry(tmp_path)
    reg.background("run-t", ProgressSnapshot(steps_done=1, started_at=1000.0))
    reg.mark_done("run-t")
    with pytest.raises(ValueError):
        reg.background("run-t", ProgressSnapshot(steps_done=2, started_at=1000.0))


# ---------------------------------------------------------------------------
# durable state round-trips across registry instances
# ---------------------------------------------------------------------------


def test_state_round_trips_across_instances(tmp_path):
    path = tmp_path / "runs.json"
    clock = FakeClock()
    reg1 = BackgroundRunRegistry(path, clock=clock)
    reg1.background(
        "run-rt", ProgressSnapshot(steps_done=5, phase="executing", started_at=1000.0, estimated_total=20, cursor=13)
    )

    # Fresh instance reads the same on-disk store.
    reg2 = BackgroundRunRegistry(path, clock=clock)
    status = reg2.status("run-rt")
    assert status.state is RunState.BACKGROUNDED
    assert status.progress.steps_done == 5
    assert status.progress.cursor == 13
    assert status.progress.estimated_total == 20

    # A reattach from the second instance is visible to a third.
    reg2.reattach("run-rt")
    reg3 = BackgroundRunRegistry(path, clock=clock)
    assert reg3.status("run-rt").state is RunState.RUNNING


def test_env_var_overrides_store_path(tmp_path, monkeypatch):
    target = tmp_path / "env-store.json"
    monkeypatch.setenv("THOMAS_BACKGROUNDING_STORE", str(target))
    reg = BackgroundRunRegistry(clock=FakeClock())
    reg.background("run-env", ProgressSnapshot(steps_done=1, started_at=1000.0))
    assert target.exists()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert "run-env" in on_disk["runs"]


def test_corrupt_store_raises_clear_error(tmp_path):
    path = tmp_path / "runs.json"
    path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(BackgroundStoreError):
        BackgroundRunRegistry(path, clock=FakeClock())
