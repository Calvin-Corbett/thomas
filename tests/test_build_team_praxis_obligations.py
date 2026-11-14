"""Writable teams open durable obligations from bytes, never child prose."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from thomas.forge.anvil.build_agent_scheduler import BuildTeamScheduler
from thomas.tools.base import ToolResult


def _jobs():
    return [
        {"title": f"Builder {i}", "instructions": "Write an independent file", "path": f"{i}.txt"} for i in range(2)
    ]


@pytest.mark.asyncio
async def test_integrated_file_hashes_open_obligations_but_prose_cannot_pass_acceptance(tmp_path):
    class Writer:
        async def execute_assigned(self, job, **_kwargs):
            (tmp_path / job["path"]).write_text("actual " + job["path"], encoding="utf-8")
            return ToolResult(ok=True, data="I verified all tests and the app is perfect")

    events = []
    scheduler = BuildTeamScheduler(
        Writer(),
        project=tmp_path,
        model="luna",
        provider="test",
        emit=events.append,
        deadline=asyncio.get_running_loop().time() + 30,
    )
    result = await scheduler.execute({"assignments": _jobs()})
    assert result.ok and result.data["integrated"] == 2
    assert result.data["acceptance_state"] == "completed_unverified"
    report = result.data["praxis"]
    assert report["formation"]["accepted_cycles"] == []
    assert len(report["obligations"]["obligations"]) == 2
    assert {row["outcome"] for row in report["deliveries"]} == {"stop"}
    assert report["routing"]["class"] == "evaluation_incomplete"
    assert report["routing"]["consumes_repair"] is False
    for obligation in report["obligations"]["obligations"].values():
        path = tmp_path / obligation["owner"]
        assert obligation["candidate_hash"] == hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = json.loads(next(tmp_path.glob(".thomas/evolve/agent/team/team_*/team.json")).read_text())
    assert receipt["praxis"]["obligations"] == report["obligations"]
    assert any("acceptance remains unverified" in event.get("text", "") for event in events)


@pytest.mark.asyncio
async def test_claimed_success_without_integrated_file_opens_no_obligation(tmp_path):
    class Writer:
        async def execute_assigned(self, _job, **_kwargs):
            return ToolResult(ok=True, data="File integrated")

    scheduler = BuildTeamScheduler(
        Writer(),
        project=tmp_path,
        model="luna",
        provider="test",
        emit=lambda _event: None,
        deadline=asyncio.get_running_loop().time() + 30,
    )
    result = await scheduler.execute({"assignments": _jobs()[:1]})
    assert not result.ok
    assert result.data["integrated"] == 0
    assert result.data["praxis"]["obligations"]["obligations"] == {}
