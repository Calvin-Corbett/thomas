"""Quota parking releases model work while keeping dependent children unfinished."""

from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

from thomas.core.praxis.formation_state import N1_RULES, Cycle
from thomas.server.praxis.coordinator import PraxisBuildCoordinator
from thomas.server.praxis.recovery import PraxisRunJournal, recover_channel
from thomas.server.praxis.run_channel import RunChannel


def test_existing_journal_schema_adds_quota_fields_without_erasing_children(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, instructions TEXT NOT NULL, updated_at REAL NOT NULL)")
        db.execute(
            "CREATE TABLE children (run_id TEXT NOT NULL, agent_id TEXT NOT NULL, plan_id TEXT NOT NULL, "
            "kind TEXT NOT NULL, title TEXT NOT NULL, brief TEXT NOT NULL, dependencies TEXT NOT NULL, "
            "state TEXT NOT NULL, model_used TEXT, attempts INTEGER NOT NULL DEFAULT 0, events TEXT NOT NULL, "
            "updated_at REAL NOT NULL, PRIMARY KEY (run_id, agent_id))"
        )
        db.execute("INSERT INTO runs VALUES ('run', 'Inspect', 1000)")
        db.execute(
            "INSERT INTO children VALUES ('run', 'child', 'child', 'review', 'Review', 'Inspect', "
            "'[]', 'running', NULL, 1, '[]', 1000)"
        )
    journal = PraxisRunJournal(path)
    assert journal.load("run")["children"][0]["agent_id"] == "child"
    journal.checkpoint("run", {"agent_id": "child", "state": "quota_wait", "resume_at": 1300})
    assert journal.load("run")["children"][0]["resume_at"] == 1300


@pytest.mark.asyncio
async def test_quota_wait_checkpoints_without_terminal_or_busy_retry(tmp_path):
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    resumed = asyncio.Event()
    attempts = 0
    states = []

    async def child(_agent_id, _kind, title, _brief):
        nonlocal attempts
        attempts += 1
        if title == "First" and attempts == 1:
            yield {
                "type": "error",
                "error": "quota exhausted",
                "retryable": True,
                "provider_credential": "opaque-account",
                "quota": {"kind": "quota", "retry_at": time.time() + 0.15, "reason": "provider_quota"},
            }
        else:
            if title == "First":
                resumed.set()
            yield {"type": "done"}

    channel = RunChannel("quota-run", child, journal=journal, state_observer=lambda _id, state: states.append(state))
    handles = await channel.spawn(
        [
            {"id": "first", "kind": "review", "title": "First", "brief": "Inspect"},
            {"id": "second", "kind": "verify", "title": "Second", "brief": "Verify", "depends_on": ["first"]},
        ]
    )
    for _ in range(50):
        if "quota_wait" in states:
            break
        await asyncio.sleep(0.001)
    first_id, second_id = (handle["agent_id"] for handle in handles)
    assert "quota_wait" in states
    assert channel.status()["metrics"]["active_agents"] == 0
    assert channel.status([second_id])["agents"][0]["state"] == "starting"
    saved = journal.load("quota-run")
    assert saved["children"][0]["state"] == "quota_wait"
    assert saved["children"][0]["resume_at"] is not None
    assert saved["children"][0]["quota_credential"] == "opaque-account"
    assert not resumed.is_set() and attempts == 1
    assert channel.status([first_id])["agents"][0]["state"] != "completed"
    await asyncio.wait_for(asyncio.gather(*channel._tasks.values()), 2)
    assert attempts == 3
    assert all(row["state"] == "completed" for row in channel.status()["agents"])


@pytest.mark.asyncio
async def test_recovery_retains_quota_deadline_and_dependent_order(tmp_path):
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    journal.admit(
        "recovery",
        "Inspect",
        [
            {"agent_id": "first", "plan_id": "first", "kind": "review", "title": "First", "brief": "Inspect"},
            {
                "agent_id": "second",
                "plan_id": "second",
                "kind": "verify",
                "title": "Second",
                "brief": "Verify",
                "dependencies": ["first"],
            },
        ],
    )
    journal.checkpoint(
        "recovery",
        {
            "agent_id": "first",
            "state": "quota_wait",
            "resume_at": time.time() + 0.15,
            "quota_credential": "opaque-account",
            "quota_reason": "provider_quota",
            "attempts": 1,
        },
    )
    calls = []

    async def child(agent_id, _kind, _title, _brief):
        calls.append(agent_id)
        yield {"type": "done"}

    assert journal.interrupted_runs() == ["recovery"]
    channel = recover_channel(PraxisRunJournal(journal.path), "recovery", child)
    assert channel.status(["first"])["agents"][0]["state"] == "quota_wait"
    await asyncio.sleep(0.02)
    assert calls == []
    await asyncio.wait_for(asyncio.gather(*channel._tasks.values()), 2)
    assert calls == ["first", "second"]
    assert channel.status(["first"])["agents"][0]["attempts"] == 2


def test_coordinator_quota_wait_is_not_acceptance_or_failure(tmp_path):
    coordinator = PraxisBuildCoordinator(
        run_id="quota",
        owners=["child"],
        cycles=[Cycle(1, "request", "acceptance")],
        log_path=tmp_path / "obligations.jsonl",
        evaluate=lambda *_: {"child": "accepted"},
        manager_id="manager",
        rules=N1_RULES,
    )
    coordinator.child_state("child", "starting")
    coordinator.child_state("child", "running")
    coordinator.child_state("child", "quota_wait")
    assert coordinator.report()["formation"]["accepted_cycles"] == []
    assert coordinator.report()["obligations"]["obligations"] == {}
