"""Crash recovery keeps finished child receipts and retries only unfinished work."""

from __future__ import annotations

import asyncio

import pytest

from thomas.server.praxis.recovery import PraxisRunJournal, recover_channel
from thomas.server.praxis.run_channel import RunChannel


def _child(agent_id: str, *, dependencies: list[str] | None = None) -> dict:
    return {
        "agent_id": agent_id,
        "plan_id": agent_id,
        "kind": "review",
        "title": agent_id,
        "brief": f"Review {agent_id}",
        "dependencies": dependencies or [],
    }


def test_admission_is_durable_and_terminal_state_cannot_regress(tmp_path):
    path = tmp_path / "praxis.sqlite3"
    first = PraxisRunJournal(path)
    first.admit("run-1", "review the project", [_child("done"), _child("pending")])
    first.checkpoint(
        "run-1",
        {
            "agent_id": "done",
            "state": "completed",
            "model_used": "gpt-5.6-sol",
            "attempts": 1,
            "events": [{"type": "done", "text": "receipt"}],
        },
    )
    second = PraxisRunJournal(path)
    assert second.interrupted_runs() == ["run-1"]
    saved = second.load("run-1")
    assert saved is not None
    assert saved["children"][0]["events"] == [{"type": "done", "text": "receipt"}]
    assert saved["children"][0]["model_used"] == "gpt-5.6-sol"
    with pytest.raises(ValueError, match="terminal"):
        second.checkpoint("run-1", {"agent_id": "done", "state": "running"})


@pytest.mark.asyncio
async def test_recovery_replays_done_child_and_runs_only_pending_dependency(tmp_path):
    journal = PraxisRunJournal(tmp_path / "praxis.sqlite3")
    journal.admit("run-1", "review the project", [_child("done"), _child("pending", dependencies=["done"])])
    journal.checkpoint(
        "run-1",
        {"agent_id": "done", "state": "completed", "events": [{"type": "done", "text": "saved"}]},
    )
    journal.checkpoint(
        "run-1",
        {"agent_id": "pending", "state": "running", "events": [{"type": "text", "text": "partial"}]},
    )
    calls = []

    async def child(agent_id, _kind, _title, _brief):
        calls.append(agent_id)
        yield {"type": "done", "text": "recovered"}

    channel = recover_channel(PraxisRunJournal(journal.path), "run-1", child)
    await asyncio.gather(*channel._tasks.values())
    rows = {row["agent_id"]: row for row in channel.status()["agents"]}
    assert calls == ["pending"]
    assert rows["done"]["events"] == [{"type": "done", "text": "saved"}]
    assert rows["pending"]["events"][-1] == {"type": "done", "text": "recovered"}
    assert all(row["state"] == "completed" for row in rows.values())
    assert channel.token


def test_duplicate_admit_does_not_erase_saved_receipt(tmp_path):
    journal = PraxisRunJournal(tmp_path / "praxis.sqlite3")
    journal.admit("run-1", "instructions", [_child("done")])
    journal.checkpoint("run-1", {"agent_id": "done", "state": "completed", "events": [{"type": "done"}]})
    journal.admit("run-1", "instructions", [_child("done")])
    assert journal.load("run-1")["children"][0]["state"] == "completed"


@pytest.mark.asyncio
async def test_live_channel_journals_admission_and_events_before_recovery(tmp_path):
    journal = PraxisRunJournal(tmp_path / "praxis.sqlite3")

    async def child(_agent_id, _kind, _title, _brief):
        yield {"type": "text", "text": "observed finding"}
        yield {"type": "done", "model_used": "gpt-5.6-luna"}

    channel = RunChannel("run-live", child, journal=journal)
    admitted = await channel.spawn([{"id": "review-1", "kind": "review", "title": "Review", "brief": "Inspect"}])
    await asyncio.gather(*channel._tasks.values())
    saved = PraxisRunJournal(journal.path).load("run-live")
    assert saved is not None
    assert saved["children"][0]["agent_id"] == admitted[0]["agent_id"]
    assert saved["children"][0]["state"] == "completed"
    assert saved["children"][0]["model_used"] == "gpt-5.6-luna"
    assert [event["type"] for event in saved["children"][0]["events"]] == ["text", "done"]
