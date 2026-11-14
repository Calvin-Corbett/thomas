"""Per-child provider choice remains exact across admission and restart."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from thomas.server.praxis.recovery import PraxisRunJournal, recover_channel
from thomas.server.praxis.run_channel import RunChannel


@pytest.mark.asyncio
async def test_chosen_model_is_passed_as_fifth_runner_argument():
    seen = []

    async def child(_id, _kind, _title, _brief, choice):
        seen.append(choice)
        yield {"type": "done"}

    channel = RunChannel("chosen", child)
    handle = (
        await channel.spawn(
            [
                {
                    "kind": "review",
                    "title": "Review",
                    "brief": "Inspect",
                    "model_choice": {"profile": "anthropic", "model_id": "claude-sonnet-4-5"},
                }
            ]
        )
    )[0]
    await channel._tasks[handle["agent_id"]]
    assert seen == [{"profile": "anthropic", "model_id": "claude-sonnet-4-5"}]
    await channel.close()


@pytest.mark.asyncio
async def test_restart_keeps_model_choice_and_does_not_fall_back(tmp_path):
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    started = asyncio.Event()

    async def first(_id, _kind, _title, _brief, _choice):
        started.set()
        await asyncio.Event().wait()
        yield {"type": "done"}

    channel = RunChannel("restart", first, journal=journal)
    handle = (
        await channel.spawn(
            [{"kind": "review", "title": "Review", "brief": "Inspect", "model_choice": {"profile": "anthropic"}}]
        )
    )[0]
    await started.wait()
    await channel.suspend()
    saved = journal.load("restart")
    assert saved["children"][0]["model_choice"] == {"profile": "anthropic"}

    seen = []

    async def resumed(_id, _kind, _title, _brief, choice):
        seen.append(choice)
        yield {"type": "done"}

    recovered = recover_channel(journal, "restart", resumed)
    assert recovered.token != channel.token
    await recovered._tasks[handle["agent_id"]]
    assert seen == [{"profile": "anthropic"}]
    assert recovered.status()["agents"][0]["state"] == "completed"
    await recovered.close()


@pytest.mark.asyncio
async def test_invalid_choice_is_rejected_before_admission(tmp_path):
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")

    async def child(*_args):
        yield {"type": "done"}

    channel = RunChannel("invalid", child, journal=journal)
    with pytest.raises(ValueError, match="invalid Build child model choice"):
        await channel.spawn(
            [{"kind": "review", "title": "Review", "brief": "Inspect", "model_choice": {"profile": "a b"}}]
        )
    assert journal.load("invalid") is None


def test_existing_journal_migrates_to_empty_choice_without_guessing_provider(tmp_path):
    path = tmp_path / "runs.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, instructions TEXT, updated_at REAL)")
        db.execute(
            "CREATE TABLE children (run_id TEXT, agent_id TEXT, plan_id TEXT, kind TEXT, title TEXT, "
            "brief TEXT, dependencies TEXT, state TEXT, model_used TEXT, attempts INTEGER, events TEXT, "
            "updated_at REAL, PRIMARY KEY (run_id, agent_id))"
        )
        db.execute("INSERT INTO runs VALUES ('old', '', 0)")
        db.execute(
            "INSERT INTO children VALUES ('old', 'child', 'unit', 'review', 'Review', 'Inspect', "
            "'[]', 'completed', NULL, 1, '[]', 0)"
        )
    journal = PraxisRunJournal(path)
    assert journal.load("old")["children"][0]["model_choice"] == {}
