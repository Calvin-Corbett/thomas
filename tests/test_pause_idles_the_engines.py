"""Pause and the engines Thomas starts by himself.

Proves ``thomas.core.pause`` is honoured by ``thomas.core.code_issue_engine``, ``thomas.core.local_agent_engine``,
``thomas.core.self_upgrade_engine``, ``thomas.core.workspace_sync_engine``, ``thomas.core.ui_workflow_engine``,
``thomas.core.testing_suite``, ``thomas.core.initiative``, ``thomas.core.aliveness`` and
``thomas.core.schedule_executor``. Each one's own tick is called directly: while paused it starts no cycle, and the
very next tick after Resume starts one, with no restart in between.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from thomas.core import pause as pause_mod


class _Recorder:
    """Stands in for ``threading.Thread``: it notes that a cycle was started and never runs it."""

    started: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._name = str(kwargs.get("name") or "")

    def start(self) -> None:
        _Recorder.started.append(self._name)


@pytest.fixture(autouse=True)
def _own_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)
    _Recorder.started = []


def _same_shape(module: str, cls: str, tmp_path, **extra: Any):
    mod = importlib.import_module(module)
    engine = getattr(mod, cls)(idle_threshold_s=0.0, cycle_interval_s=1.0, log_path=tmp_path / "log.jsonl", **extra)
    engine._enabled = True
    engine._last_cycle_ts = -1e9
    return mod, engine


def _testing_suite(tmp_path):
    mod = importlib.import_module("thomas.core.testing_suite")
    engine = mod.TestingSuite()
    engine._last_cycle_ts = -1e9
    engine.is_idle = lambda: True  # type: ignore[method-assign]
    return mod, engine


def _initiative(tmp_path, monkeypatch):
    mod = importlib.import_module("thomas.core.initiative")
    engine = mod.InitiativeEngine()
    engine.is_idle = lambda: True  # type: ignore[method-assign]
    monkeypatch.setattr(engine, "_maybe_daily_summary", lambda: None)
    persistence = importlib.import_module("thomas.core.persistence")

    class _Goals:
        def open_goals(self) -> list[dict[str, Any]]:
            return [{"id": "goal-0001", "text": "tidy"}]

    monkeypatch.setattr(persistence, "get_persistence", lambda: _Goals())
    monkeypatch.setattr(mod, "pick_highest_roi", lambda goals: goals[0] if goals else None)
    return mod, engine


CASES = {
    "code_issue_engine": lambda p, m: _same_shape("thomas.core.code_issue_engine", "CodeIssueEngine", p),
    "local_agent_engine": lambda p, m: _same_shape("thomas.core.local_agent_engine", "LocalAgentEngine", p),
    "self_upgrade_engine": lambda p, m: _same_shape("thomas.core.self_upgrade_engine", "SelfUpgradeEngine", p),
    "workspace_sync_engine": lambda p, m: _same_shape(
        "thomas.core.workspace_sync_engine", "WorkspaceSyncEngine", p, repo_root=p
    ),
    "ui_workflow_engine": lambda p, m: _same_shape("thomas.core.ui_workflow_engine", "UIWorkflowEngine", p, ui_root=p),
    "testing_suite": lambda p, m: _testing_suite(p),
    "initiative": _initiative,
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_an_engine_starts_no_cycle_while_paused_and_starts_one_after_resume(name, tmp_path, monkeypatch):
    mod, engine = CASES[name](tmp_path, monkeypatch)
    monkeypatch.setattr(mod.threading, "Thread", _Recorder)

    pause_mod.pause("test")
    engine._tick()
    engine._tick()
    assert _Recorder.started == []

    pause_mod.resume()
    engine._tick()
    assert len(_Recorder.started) == 1


def test_the_idle_sweep_skips_its_tick_while_paused_and_keeps_its_timer(monkeypatch):
    import threading

    from thomas.core import aliveness

    loop = aliveness.AlivenessLoop()
    ticks: list[int] = []
    seen_paused: list[bool] = []
    done = threading.Event()

    def fake_tick(*, idle_seconds: float = 0.0, **_: Any) -> None:
        ticks.append(1)

    monkeypatch.setattr(loop, "tick", fake_tick)
    monkeypatch.setattr(loop, "_idle_seconds", lambda: 0.0)
    real_paused = aliveness.paused

    def watching() -> bool:
        value = real_paused()
        seen_paused.append(value)
        if len(seen_paused) == 3:
            pause_mod.resume()  # the sweep's own next pass sees Resume without a restart
        if len(ticks) >= 1:
            done.set()
        return value

    monkeypatch.setattr(aliveness, "paused", watching)
    pause_mod.pause("test")
    loop.start(interval_s=0.01)
    assert done.wait(10)
    loop.stop()
    assert seen_paused[:3] == [True, True, True]
    assert ticks


def test_a_scheduled_job_that_falls_due_while_paused_waits_and_runs_after_resume(tmp_path):
    from thomas.core import schedule_executor

    ran: list[str] = []
    scheduler = schedule_executor.SharedFileScheduler(
        execute_fn=lambda goal, channel: ran.append(goal), schedule_path=tmp_path / "schedules.json", auto_start=False
    )
    try:
        scheduler.add_task("t1", "* * * * *", "say hi")
        with scheduler._lock:
            scheduler._tasks["t1"].next_run_at = "2000-01-01T00:00:00+00:00"
        pause_mod.pause("test")
        scheduler._poll_once()
        assert scheduler._tasks["t1"].next_run_at == "2000-01-01T00:00:00+00:00"
        pause_mod.resume()
        scheduler._poll_once()
        scheduler._executor.shutdown(wait=True)
        assert ran == ["say hi"]
    finally:
        scheduler.stop()
