"""A large Build team is admitted in resource-sized waves and keeps a receipt."""

from __future__ import annotations

import asyncio
import json

import pytest

from thomas.core.praxis import allowance as allowance_module
from thomas.core.praxis.allowance import BuildAllowance
from thomas.forge.anvil.build_agent_scheduler import BuildTeamScheduler
from thomas.tools.base import ToolResult


def test_plan_size_does_not_become_an_admission_limit():
    allowance = BuildAllowance.for_machine(100, cpu_count=1, available_memory_bytes=128 * 1024 * 1024)
    assert allowance.assignments == 100
    assert allowance.concurrent == 2
    assert allowance.waves == 50
    assert allowance.final_report_reserved
    assert BuildAllowance.for_machine(101, cpu_count=1, available_memory_bytes=0).concurrent == 1


@pytest.mark.asyncio
async def test_scheduler_uses_resource_waves_and_reports_allowance(tmp_path, monkeypatch):
    monkeypatch.setattr(allowance_module, "_available_memory", lambda: 128 * 1024 * 1024)
    monkeypatch.setattr(allowance_module.os, "cpu_count", lambda: 1)
    active = peak = 0

    class Writer:
        async def execute_assigned(self, job, **_options):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01)
                (tmp_path / job["path"]).write_text("built", encoding="utf-8")
                return ToolResult(ok=True, data="integrated")
            finally:
                active -= 1

    scheduler = BuildTeamScheduler(
        Writer(),
        project=tmp_path,
        model="luna",
        provider="test",
        emit=lambda _event: None,
        deadline=asyncio.get_running_loop().time() + 30,
    )
    jobs = [{"title": f"Builder {n}", "instructions": "Build file", "path": f"{n}.txt"} for n in range(9)]
    result = await scheduler.execute({"assignments": jobs})
    assert result.ok and result.data["integrated"] == 9
    assert result.data["allowance"]["concurrent"] == peak == 2
    assert result.data["allowance"]["waves"] == 5
    receipt = json.loads(open(result.data["receipt"], encoding="utf-8").read())
    assert receipt["allowance"] == result.data["allowance"]


@pytest.mark.asyncio
async def test_deadline_still_returns_durable_final_receipt(tmp_path):
    class Writer:
        async def execute_assigned(self, _job, **_options):
            await asyncio.Event().wait()

    scheduler = BuildTeamScheduler(
        Writer(),
        project=tmp_path,
        model="luna",
        provider="test",
        emit=lambda _event: None,
        deadline=asyncio.get_running_loop().time() + 0.03,
    )
    result = await scheduler.execute(
        {"assignments": [{"title": "Builder", "instructions": "Build file", "path": "file.txt"}]}
    )
    assert not result.ok
    assert result.data and result.data["receipt"] in result.error
    receipt = json.loads(open(result.data["receipt"], encoding="utf-8").read())
    assert receipt["state"] == "failed"
    assert receipt["allowance"]["final_report_reserved"]
