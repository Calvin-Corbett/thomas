"""A turn-on that fails part way leaves no recovered helper running with nothing to stop it."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from thomas.server.praxis import launch, startup
from thomas.server.praxis.recovery import PraxisRunJournal
from thomas.server.praxis.run_channel import RunChannelRegistry


def _journal_with_two_runs(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    journal = PraxisRunJournal(tmp_path / "praxis" / "runs.sqlite3")
    for run_id in ("r1", "r2"):
        journal.record_launch(
            run_id,
            {
                "project_root": str(project.resolve()),
                "family": "gpt",
                "model_id": "gpt-5.6-sol",
                "reviewer_model": "gpt-5.6-luna",
                "dispatch_model": "codex:gpt",
                "praxis_reviewer_profile": "",
                "praxis_reviewer_model": "",
            },
        )
        journal.admit(
            run_id,
            "Inspect",
            [
                {
                    "agent_id": f"{run_id}-child",
                    "plan_id": "unit",
                    "kind": "review",
                    "title": "Review",
                    "brief": "Inspect",
                    "dependencies": [],
                    "model_choice": {"profile": "openai_codex", "model_id": "gpt-5.6-luna"},
                }
            ],
        )
        journal.checkpoint(run_id, {"agent_id": f"{run_id}-child", "state": "running", "attempts": 1, "events": []})
    return journal


def _helpers() -> list[asyncio.Task]:
    return [t for t in asyncio.all_tasks() if t.get_name().endswith(":recovered") and not t.done()]


def _setup(tmp_path, monkeypatch, fail_on_load_call, error):
    journal = _journal_with_two_runs(tmp_path)
    monkeypatch.setattr(startup, "user_praxis_root", lambda: tmp_path)

    def factory(_app, _project, _settings, _run_id):
        async def child(*_args, **_kwargs):
            await asyncio.Event().wait()
            yield {"type": "done"}

        return child

    monkeypatch.setattr(launch, "build_dispatching_child_runner", factory)
    real_load = PraxisRunJournal.load
    calls = 0

    def load(self, run_id):
        nonlocal calls
        calls += 1
        if calls == fail_on_load_call:
            raise error
        return real_load(self, run_id)

    monkeypatch.setattr(PraxisRunJournal, "load", load)


@pytest.mark.asyncio
async def test_a_failure_that_escapes_the_scan_stops_the_helpers_already_taken_in(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, 3, sqlite3.OperationalError("database is locked"))
    registry = RunChannelRegistry()
    app: dict = {}
    try:
        startup.recover_interrupted_runs(app, registry)
    except sqlite3.Error:
        pass
    await asyncio.sleep(0.05)
    assert _helpers() == []


@pytest.mark.asyncio
async def test_an_unforeseen_failure_leaves_nothing_adopted_and_no_helper(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, 3, ZeroDivisionError("boom"))
    registry = RunChannelRegistry()
    with pytest.raises(ZeroDivisionError):
        startup.recover_interrupted_runs({}, registry)
    await asyncio.sleep(0.05)
    assert _helpers() == []
    assert registry._runs == {}
